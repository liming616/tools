"""产地快打 v2.0.1 主应用组装。

职责：剪贴板轮询、全局连击钩子、文本识别入列表、流向产品匹配、
Excel 导出、未导出数据持久化。
"""

import ctypes
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, filedialog

from paths import app_dir
from logger import get_logger, log_exception
from crash_handler import install_crash_handler, show_error_dialog
from single_instance import acquire_single_instance
from config_manager import (
    load_config, save_config, load_app_config,
    get_flow_strategies, get_default_temperature,
)
from template_manager import (
    get_list_headers, get_export_categories,
    flatten_export_fields, empty_fields_dict,
)
from recognition import normalize_text, recognize_batch, recognize_line
from flow_product import resolve_product
from sender_manager import SenderManager
from parser import configure_surnames
from data_store import (
    save_collected_by_template, load_collected_by_template,
    clear_collected_by_template,
)
from clipboard_worker import ClipboardWorker
from clipboard_safe import send_ctrl_c
from hook_engine import MouseHook
from excel_exporter import write_export_excel
from app_frame import AppFrame
from dialogs import SenderConfigDialog

logger = get_logger("moshidadan.main")


class App:
    """产地快打主应用组装核心。

    通过回调注入 AppFrame，业务逻辑在此层完成。
    """

    def __init__(self, config, app_config):
        self._config = config
        self._app_config = app_config
        self._template_key = config.get("selected_template", "JD_MONTHLY")
        self._save_dir = str(config.get("save_dir", "") or "").strip()
        self._list_headers = list(get_list_headers(self._template_key, app_config))
        self._row_data = []
        self._auto_recognize = bool(config.get("auto_recognize", False))
        self._combo_copy = bool(config.get("combo_copy", True))
        self._sender_mgr = SenderManager(config)

        self._frame = AppFrame(config, app_config)
        self._frame._list_headers = self._list_headers

        # 注入回调
        self._frame.on_template_changed = self._on_template_changed
        self._frame.on_auto_toggle = self._on_auto_toggle
        self._frame.on_combo_toggle = self._on_combo_toggle
        self._frame.on_recognize = self._on_recognize
        self._frame.on_save = self._export_excel
        self._frame.on_config_clicked = self._on_config_clicked
        self._frame.on_save_dir_clicked = self._on_save_dir_clicked
        self._frame.on_help_clicked = self._on_help_clicked
        self._frame.on_cell_edited = self._on_cell_edited
        self._frame.on_row_checked = self._on_row_checked
        self._frame.on_select_all = self._on_select_all
        self._frame.on_delete_selected = self._delete_selected_rows

        # 剪贴板与连击
        self._clipboard_worker = ClipboardWorker()
        self._clipboard_worker.start()
        self._mouse_hook = None
        self._hook_active = False
        self._hook_drain_id = None
        self._dc_click_count = 0
        self._dc_last_click = 0.0
        self._dc_last_x = 0
        self._dc_last_y = 0
        self._dc_fire_id = None
        self._dc_cooldown_until = 0.0
        self._last_clipboard_seq = None

        self._restore_saved_data()
        self._frame.protocol("WM_DELETE_WINDOW", self._on_close)

        # 启动监听
        self._frame.after(300, self._poll_clipboard)
        if self._combo_copy:
            self._start_mouse_capture()

    # ---------- 字段合并 ----------

    def _merge_fields(self, fields, sender_fields=None):
        """合并识别字段 + 寄件人 + 温层 + 付款方式 + 流向产品。"""
        merged = dict(empty_fields_dict())
        merged.update(fields)
        if sender_fields is None:
            sender_fields = self._sender_mgr.get_selected_sender_fields()
        merged.update(sender_fields)
        merged["temperature_layer"] = (
            merged.get("temperature_layer") or self._sender_mgr.get_temperature_layer()
        )
        merged["payment_method"] = (
            merged.get("payment_method")
            or self._sender_mgr.get_payment_method(self._template_key)
        )
        if not merged.get("delivery_product"):
            strategies = get_flow_strategies(self._app_config, self._template_key)
            if strategies:
                # 优先使用 config.json 中选中的策略；未选中或已失效时回退到内置第一条，
                # 保证 JD_OFFICIAL 等未写入 selected_strategy 的模板也能读取流向配置。
                strategy_id = self._sender_mgr.get_selected_strategy_id(self._template_key)
                strategy = next(
                    (s for s in strategies if s.get("id") == strategy_id), None
                ) or strategies[0]
                merged["delivery_product"] = resolve_product(
                    strategy, merged.get("province", ""), merged.get("city", "")
                )
        return merged

    # ---------- 列表 ----------

    def _append_row(self, fields):
        """向列表添加一行：构建显示行并插入 Treeview。"""
        row = {"fields": fields, "raw": "", "selected": False}
        self._row_data.append(row)
        serial = len(self._row_data)
        values = self._frame.build_row(fields, serial=serial, selected=False)
        self._frame.insert_row(values)
        self._frame.update_select_header()
        self._frame.set_status(f"已识别 {len(self._row_data)} 条")
        return row

    def _rebuild_list(self):
        """按当前 _row_data 重建列表。"""
        self._frame.clear_rows()
        for i, row in enumerate(self._row_data, 1):
            values = self._frame.build_row(
                row["fields"], serial=i, selected=bool(row.get("selected"))
            )
            self._frame.insert_row(values)
        self._frame.update_select_header()

    def _on_cell_edited(self, item, col, value):
        """单元格编辑后同步到 _row_data。

        col 是 Treeview 列标识符（形如 "#2"），先转为表头文本再映射字段键；
        行号取 item 在树中的 0-based 位置，避免编辑值丢失或写错行。
        """
        try:
            row_index = self._frame._tree.index(item)
            header = self._frame._tree.heading(str(col or ""), "text")
        except Exception:
            logger.warning("单元格编辑同步失败: col=%s", col)
            return
        if not (0 <= row_index < len(self._row_data)):
            return
        key = self._field_key(header)
        if key:
            self._row_data[row_index]["fields"][key] = value

    # ---------- 剪贴板 ----------

    def _poll_clipboard(self):
        """主线程轮询剪贴板序列号变化。"""
        try:
            seq = self._clipboard_worker.get_latest_sequence()
            if seq is not None and seq != self._last_clipboard_seq:
                self._last_clipboard_seq = seq
                text = self._clipboard_worker.get_latest_text()
                if text and text.strip():
                    self.handle_clipboard_text(text)
        except Exception as e:
            logger.warning("剪贴板轮询异常: %s", e)
        finally:
            self._frame.after(400, self._poll_clipboard)

    def handle_clipboard_text(self, text):
        """剪贴板新文本：按焦点路由到寄件人/收件人框，否则维持现状入列表。"""
        normalized = normalize_text(text)
        if not normalized:
            return
        target = self._frame.get_focus_target()
        if target == "sender":
            self._frame.set_sender_text(normalized)
            return
        if target == "receiver":
            self._frame.append_receiver(normalized)
            return
        if self._auto_recognize:
            lines = recognize_batch(normalized)
            fields = lines[0] if lines else {}
            if fields:
                self._append_row(self._merge_fields(fields))
        else:
            self._frame.append_receiver(normalized)

    # ---------- 连击复制 ----------

    def _start_mouse_capture(self):
        """启动全局鼠标钩子连击采集。"""
        try:
            self._mouse_hook = MouseHook()
            self._hook_active = bool(self._mouse_hook.start())
            if self._hook_active:
                self._frame.after(10, self._drain_mouse_hook)
                logger.info("连击采集已启动（WH_MOUSE_LL 钩子）")
            else:
                self._mouse_hook = None
        except Exception as e:
            logger.warning("连击钩子启动失败: %s", e)
            self._mouse_hook = None

    def _stop_mouse_capture(self):
        """停止连击采集。"""
        self._hook_active = False
        if self._mouse_hook is not None:
            try:
                self._mouse_hook.stop()
            except Exception:
                pass
            self._mouse_hook = None
        if self._hook_drain_id is not None:
            try:
                self._frame.after_cancel(self._hook_drain_id)
            except Exception:
                pass
            self._hook_drain_id = None
        if self._dc_fire_id is not None:
            try:
                self._frame.after_cancel(self._dc_fire_id)
            except Exception:
                pass
            self._dc_fire_id = None
        self._dc_click_count = 0

    def _drain_mouse_hook(self):
        """消费钩子队列的点击事件。"""
        self._hook_drain_id = None
        if not (self._hook_active and self._combo_copy):
            return
        try:
            hook = self._mouse_hook
            if hook is not None:
                guard = 0
                while guard < 50:
                    ev = hook.poll()
                    if ev is None:
                        break
                    t, x, y = ev
                    self._on_mouse_down(x, y, t)
                    guard += 1
        except Exception as e:
            logger.warning("钩子处理异常: %s", e)
        finally:
            if self._hook_active and self._combo_copy:
                self._hook_drain_id = self._frame.after(10, self._drain_mouse_hook)

    def _on_mouse_down(self, x, y, now):
        """识别连击序列，达到双击及以上则延迟触发复制。"""
        try:
            my_hwnd = int(self._frame.frame(), 16)
        except Exception:
            my_hwnd = None
        fg = ctypes.windll.user32.GetForegroundWindow()
        if my_hwnd and fg == my_hwnd:
            return

        time_diff = now - self._dc_last_click
        same_burst = (
            self._dc_click_count > 0
            and 0 < time_diff < 0.6
            and abs(x - self._dc_last_x) < 20
            and abs(y - self._dc_last_y) < 20
        )
        self._dc_click_count = self._dc_click_count + 1 if same_burst else 1
        if self._dc_click_count >= 2:
            self._schedule_dc_fire()
        self._dc_last_click = now
        self._dc_last_x = x
        self._dc_last_y = y

    def _schedule_dc_fire(self):
        """调度连击稳态触发。"""
        if self._dc_fire_id is not None:
            try:
                self._frame.after_cancel(self._dc_fire_id)
            except Exception:
                pass
        self._dc_fire_id = self._frame.after(450, self._dc_fire)

    def _dc_fire(self):
        """连击稳定后：发 Ctrl+C -> 等待剪贴板变化 -> 处理。"""
        self._dc_fire_id = None
        if not (self._combo_copy and self._hook_active):
            return
        if time.time() < self._dc_cooldown_until:
            self._dc_click_count = 0
            return
        self._dc_cooldown_until = time.time() + 0.8
        self._dc_click_count = 0
        prev_seq = self._clipboard_worker.get_latest_sequence()
        if send_ctrl_c():
            deadline = time.time() + 1.0
            while time.time() < deadline:
                new_seq = self._clipboard_worker.get_latest_sequence()
                if new_seq is not None and new_seq != prev_seq:
                    text = self._clipboard_worker.get_latest_text()
                    if text and text.strip():
                        self._last_clipboard_seq = new_seq
                        self.handle_clipboard_text(text)
                    break
                time.sleep(0.05)

    # ---------- 文本识别按钮 ----------

    def _on_recognize(self):
        """文本识别按钮：按行批量识别收件框内容。"""
        sender_text = self._frame.get_sender_text()
        sender_fields = self._resolve_sender_fields(sender_text)
        text = self._frame.get_receiver_text()
        if not text:
            self._frame.set_status("收件人文本为空")
            return
        for fields in recognize_batch(text):
            self._append_row(self._merge_fields(fields, sender_fields))
        # 识别完成后清空收件框，防止同一批文本被再次识别导致重复
        self._frame.clear_receiver_text()
        self._frame.set_status(f"已识别 {len(self._row_data)} 条")

    # ---------- 导出 ----------

    def _export_excel(self):
        """导出 Excel：双行带色表头，成功后清空列表与持久化。"""
        if not self._row_data:
            messagebox.showinfo("提示", "列表无数据可导出")
            return
        categories = get_export_categories(self._template_key, self._app_config)
        if not categories:
            messagebox.showinfo("提示", "当前模板暂未配置可导出字段")
            return
        # 必填校验：收件人姓名、地址必填，手机/座机二选一，缺失则阻断导出
        invalid_msg = self._validate_required_rows()
        if invalid_msg:
            messagebox.showwarning("校验未通过", invalid_msg)
            return
        headers = flatten_export_fields(categories)
        rows = []
        for row in self._row_data:
            fields = row["fields"]
            rows.append([str(fields.get(self._field_key(h), "") or "") for h in headers])

        if self._save_dir:
            fname = time.strftime("产地快打_%Y%m%d_%H%M%S.xlsx")
            path = os.path.join(self._save_dir, fname)
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")]
            )
        if not path:
            return

        dropdown = (
            (self._app_config.get("template_configs", {})
             .get(self._template_key, {}) or {})
            .get("dropdown_options")
        )
        write_export_excel(path, categories, rows, dropdown)
        self._row_data = []
        frame = getattr(self, "_frame", None)
        if frame is not None:
            try:
                frame.clear_rows()
                frame.update_select_header()
            except Exception:
                pass
        clear_collected_by_template(self._template_key)
        logger.info("导出成功 | %s | %d 条", path, len(rows))
        messagebox.showinfo("导出成功", f"已导出 {len(rows)} 条到:\n{path}")

    # ---------- 配置弹窗 / 保存目录 ----------

    def _on_config_clicked(self):
        """打开寄件信息配置弹窗。"""
        dialogs = SenderConfigDialog(
            self._frame, self._app_config, self._config,
            self._template_key, self._on_config_saved,
        )
        dialogs.wait_window()

    def _on_config_saved(self, config):
        """寄件配置保存后持久化并刷新寄件人。"""
        self._config = config
        self._sender_mgr = SenderManager(config)
        save_config(config)

    def _on_save_dir_clicked(self):
        """选择文件保存目录。"""
        d = filedialog.askdirectory()
        if d:
            self._save_dir = d
            self._config["save_dir"] = d
            save_config(self._config)
            self._frame.set_status(f"保存目录: {d}")

    def _on_help_clicked(self):
        """帮助提示。"""
        messagebox.showinfo(
            "帮助",
            "选择寄件人后粘贴文本，自动识别开启时实时入列表；\n"
            "关闭时文本进入「收」框，点「文本识别」按行批量识别。",
        )

    def _on_template_changed(self, key):
        """模板切换：保存旧模板数据并分组，切换到新模板回显该模板数据。"""
        old_key = self._template_key
        save_collected_by_template(old_key, self._row_data)
        self._template_key = key
        self._list_headers = list(get_list_headers(key, self._app_config))
        self._frame._list_headers = self._list_headers
        self._row_data = load_collected_by_template(key)
        self._rebuild_list()
        self._frame.set_status(f"已识别 {len(self._row_data)} 条")
        self._config["selected_template"] = key
        save_config(self._config)

    def _on_auto_toggle(self, enabled):
        """自动识别开关。"""
        self._auto_recognize = bool(enabled)
        self._config["auto_recognize"] = self._auto_recognize
        save_config(self._config)

    def _on_combo_toggle(self, enabled):
        """连击复制开关。"""
        self._combo_copy = bool(enabled)
        self._config["combo_copy"] = self._combo_copy
        save_config(self._config)
        if self._combo_copy and not self._hook_active:
            self._start_mouse_capture()
        elif not self._combo_copy and self._hook_active:
            self._stop_mouse_capture()

    # ---------- 持久化 ----------

    def _restore_saved_data(self):
        """启动回显当前模板上次未导出数据。"""
        self._row_data = load_collected_by_template(self._template_key)
        if self._row_data:
            self._rebuild_list()
            self._frame.set_status(f"已恢复 {len(self._row_data)} 条未导出数据")

    def _on_close(self):
        """关闭：保存未导出数据与配置，若有数据提示确认。"""
        if self._row_data:
            save_collected_by_template(self._template_key, self._row_data)
            if not messagebox.askyesno(
                "确认退出", f"列表还有 {len(self._row_data)} 条未导出数据，确定退出？"
            ):
                return
        # 关闭前把寄件人卡片编辑内容落盘到 sender_profiles
        frame = getattr(self, "_frame", None)
        if frame is not None and hasattr(frame, "flush_sender_profile"):
            try:
                frame.flush_sender_profile()
            except Exception:
                pass
        save_config(self._config)
        self._stop_mouse_capture()
        self._clipboard_worker.stop()
        self._frame.destroy()

    # ---------- 字段映射 ----------

    @staticmethod
    def _field_key(header):
        mapping = {
            "收件人姓名": "name",
            "收货人": "name",
            "联系方式": "phone",
            "收件人手机": "phone",
            "收件人座机": "landline",
            "收件人地址": "full_address",
            "详细地址(省+市+区/县+街道号+门牌号)": "full_address",
            "物品类型": "items_text",
            "时效产品": "delivery_product",
            "产品类型": "delivery_product",
            "温层": "temperature_layer",
            "付款方式": "payment_method",
            "支付方式": "payment_method",
            "总件数": "item_count",
            "件数": "item_count",
            "面单备注": "notes",
            "运单备注": "notes",
            "寄件人姓名": "sender_name",
            "寄件人手机": "sender_phone",
            "寄件人座机": "sender_landline",
            "寄件人地址": "sender_address",
        }
        return mapping.get(header, "")

    def _validate_required_rows(self) -> str:
        """校验列表必填项：收件人姓名、地址必填，手机/座机二选一。

        Returns:
            返回空字符串表示校验通过；否则返回带行号的中文提示。
        """
        for idx, row in enumerate(self._row_data, start=1):
            fields = row.get("fields") or {}
            name = str(fields.get("name") or "").strip()
            address = str(fields.get("full_address") or "").strip()
            phone = str(fields.get("phone") or "").strip()
            landline = str(fields.get("landline") or "").strip()
            if not name:
                return f"第 {idx} 条：收件人姓名必填"
            if not address:
                return f"第 {idx} 条：收件人地址必填"
            if not (phone or landline):
                return f"第 {idx} 条：收件人手机、座机至少填一项"
        return ""

    def _resolve_sender_fields(self, sender_text: str) -> dict:
        """解析寄件人文本框为结构化字段；为空则回退默认寄件人信息。

        返回的字段会注入到「文本识别」生成的每一行列表数据中。
        """
        stripped = (sender_text or "").strip()
        if stripped:
            fields = self._parse_sender_fields(stripped)
            # 写回当前选中的寄件人档案，供后续导出复用
            self._sender_mgr.update_selected_sender_fields(fields)
            return fields
        return self._default_sender_fields()

    def _parse_sender_fields(self, text: str) -> dict:
        """使用现有解析器解析寄件人文本，映射为寄件人结构化字段。"""
        parsed = recognize_line(text)
        return {
            "sender_name": (parsed.get("name") or "").strip(),
            "sender_phone": (parsed.get("phone") or "").strip(),
            "sender_landline": (parsed.get("landline") or "").strip(),
            "sender_address": (parsed.get("full_address") or "").strip(),
            "sender_company": "",
            "sender_warehouse_code": "",
        }

    def _default_sender_fields(self) -> dict:
        """从寄件人信息配置读取默认寄件人字段。"""
        default = self._config.get("default_sender") or {}
        return {
            "sender_name": str(default.get("sender_name") or "").strip(),
            "sender_phone": str(default.get("sender_phone") or "").strip(),
            "sender_landline": str(default.get("sender_landline") or "").strip(),
            "sender_address": str(default.get("sender_address") or "").strip(),
            "sender_company": "",
            "sender_warehouse_code": "",
            "temperature_layer": str(default.get("temperature_layer") or "").strip(),
            "payment_method": str(default.get("payment_method") or "").strip(),
        }

    def _on_row_checked(self, item, checked: bool) -> None:
        """单行勾选切换后同步到 _row_data。"""
        try:
            row_index = self._frame._tree.index(item)
        except Exception:
            return
        if 0 <= row_index < len(self._row_data):
            self._row_data[row_index]["selected"] = bool(checked)

    def _on_select_all(self, checked: bool) -> None:
        """全选/全不选后同步到 _row_data。"""
        for row in self._row_data:
            row["selected"] = bool(checked)

    def _delete_selected_rows(self) -> None:
        """删除勾选的行并持久化当前模板数据。"""
        selected = [row for row in self._row_data if row.get("selected")]
        if not selected:
            messagebox.showinfo("提示", "请先勾选要删除的数据")
            return
        if not messagebox.askyesno("确认删除", f"确定删除选中的 {len(selected)} 条数据？"):
            return
        self._row_data = [row for row in self._row_data if not row.get("selected")]
        self._rebuild_list()
        self._frame.set_status(f"已删除 {len(selected)} 条")
        save_collected_by_template(self._template_key, self._row_data)


def main() -> None:
    """主入口：单实例 + 崩溃处理 + 加载配置 + 启动主窗口。"""
    if sys.platform != "win32":
        logger.error("产地快打仅支持 Windows")
        return
    handle = acquire_single_instance()
    if handle is None:
        logger.info("已有实例运行，跳过启动")
        return
    install_crash_handler()
    config = load_config()
    app_config = load_app_config()
    configure_surnames(app_config)
    try:
        app = App(config, app_config)
        app._frame.mainloop()
    except Exception as e:
        log_exception(logger, e, "应用启动失败")
        show_error_dialog("启动失败", f"产地快打无法启动：{e}", str(e))


if __name__ == "__main__":
    main()
