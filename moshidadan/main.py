"""
产地快打 v7 — 生产版
剪贴板实时预览 + 全局连击复制转储 + 生产级稳定性保障

流程:
  1. 用户在任何应用中 Ctrl+C 复制文本 → 预览区实时显示
  2. 全局连击：在任意应用中双击/三击选中文本 → 自动发送 Ctrl+C → 转储
  3. 用户点击「转储」→ 文本追加到收集区
  4. 可「复制全部」或「清空」

生产级特性:
  - 结构化日志（轮转、自动清理）
  - 全局异常捕获与崩溃报告
  - 配置 Schema 验证与自动修复
  - 剪贴板操作重试机制
  - 轮询回路看门狗（自动恢复）
  - 数据自动保存（防丢失）
  - 错误率监控与自动降级
  - 友好的中文错误提示
  - 启动环境自检
"""

import sys
import os
import time
import json
import ctypes
import ctypes.wintypes as w
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional

# ======================== 内部模块 ========================

from paths import app_dir, resource_path
from config_manager import load_config, save_config, reset_config, DEFAULT_CONFIG, load_app_config
from logger import get_logger, log_exception
from crash_handler import install_crash_handler, show_error_dialog, show_warning_dialog

# 地址解析
from parser import parse_order, OrderInfo, score_fields, is_low_confidence
from address_parser import parse_address_safe, ParsedAddress

# 模版管理
from template_manager import (
    DEFAULT_HEADERS, map_headers_to_fields,
    build_row_tuple, empty_fields_dict, compute_column_width,
)

# 安全剪贴板操作
from clipboard_safe import (
    send_ctrl_c, get_foreground_title, is_wechat_active,
)

# 剪贴板工作线程与单实例互斥
from clipboard_worker import ClipboardWorker
from single_instance import acquire_single_instance
from excel_exporter import EXPORT_FIELD_MAP, flatten_categories, write_export_excel

# 全局低级鼠标钩子（连击采集）
from hook_engine import MouseHook

# ======================== 日志 ========================

logger = get_logger("moshidadan.main")

# 单实例互斥句柄（进程存活期间保持引用）
_single_instance_handle: Optional[int] = None

# ======================== Windows API（仅用于鼠标检测）========================

user32 = ctypes.windll.user32
VK_LBUTTON = 0x01


# ======================== 主应用 ========================

# 预制信息弹窗固定展示字段；其中手机/座机二选一必填，其余字段必填
PREFILL_FIELDS = ["寄件人姓名", "寄件人手机", "寄件人座机", "寄件人地址", "物品类型", "时效产品"]
PREFILL_REQUIRED_FIELDS = ["寄件人姓名", "寄件人地址", "物品类型", "时效产品"]


def _is_receiver_field(field_path: Optional[str]) -> bool:
    """是否在收集列表显示该列。

    仅显示「收件人（从微信文本解析）」字段；寄件人/预制字段（sender_*）
    与未映射列（发货仓、时效、温层、订单号等）一律隐藏，导出时再拼回。
    """
    if not field_path:
        return False
    if field_path.startswith("sender_"):
        return False
    return True


class App:
    def __init__(self, config: dict):
        self.config = config
        self._clipboard_worker = ClipboardWorker()
        self._clipboard_worker.start()
        self.app_config = load_app_config()
        self._app_title = "{} {}".format(
            self.app_config.get("app_name", "产地快打"),
            self.app_config.get("version", "v1.0.0"),
        )
        self._template_key = self.app_config.get("templates", {}).get("default", "JD")
        self._template_options = self.app_config.get("templates", {}).get("options", [])
        self._selected_export_fields = self._load_export_field_selection()
        self._running = False
        self._last_clipboard = ""
        self._capture_count = 0
        self._dc_enabled = self.config.get("double_click_copy", True)

        # ---- 健康监控 ----
        self._error_count = 0
        self._error_timestamps: list[float] = []
        self._poll_healthy = True
        self._last_poll_time = 0.0
        self._max_errors_per_minute = self.config.get("max_errors_per_minute", 10)
        self._degraded = False      # 降级模式标志
        self._dc_paused = False     # 连击功能暂停标志
        self._poll_count = 0        # 轮询计数器（用于心跳日志）

        # ---- 连击检测状态 ----
        self._mouse_was_down = False
        self._mouse_last_click = 0.0
        self._mouse_last_x = 0
        self._mouse_last_y = 0
        self._dc_poll_id: Optional[str] = None
        self._dc_cooldown_until = 0.0  # 连击冷却截止时间（防止重复触发）
        self._dc_click_count = 0        # 当前连击序列中的点击次数
        self._dc_fire_id: Optional[str] = None  # 延迟触发的 after() 句柄

        # ---- 低级鼠标钩子状态 ----
        self._mouse_hook: Optional[MouseHook] = None  # WH_MOUSE_LL 钩子实例
        self._mouse_hook_id: Optional[str] = None     # 钩子队列消费 after() 句柄
        self._hook_active = False                     # 钩子是否成功启用
        self._status_restore_id: Optional[str] = None # 状态栏恢复定时器句柄

        # 连击判定参数（从配置读取）
        self._dc_interval = self.config.get("double_click_interval_ms", 500) / 1000.0
        self._dc_pos_tolerance = self.config.get("double_click_pos_tolerance", 20)
        # 连击稳定延迟：等待可能到来的第 3 次点击（三连击选行），再触发一次复制
        self._dc_settle_ms = max(350, int(self._dc_interval * 1000 * 0.8))
        self._dc_cooldown_s = 0.8

        # ---- 连击历史（用于诊断）----
        self._dc_history: list[tuple[float, int, int]] = []  # [(timestamp, x, y), ...]

        # ---- 自动保存 ----
        self._auto_save_interval = self.config.get("auto_save_interval_s", 120) * 1000
        self._auto_save_id: Optional[str] = None
        self._data_file = os.path.join(app_dir(), "collected_data.json")
        self._dirty = False  # 数据是否有未保存的变更

        # ---- 收集表格状态 ----
        self._count_var: Optional[tk.StringVar] = None
        self._stats_var: Optional[tk.StringVar] = None
        self._collect_table: Optional[ttk.Treeview] = None

        # ---- 动态列 & 模版 ----
        self._row_data: list[dict] = []              # [{"fields": {...}, "raw": str}, ...]
        self._template_headers: list[str] = []        # 当前列标题（完整模版列）
        self._mapped_fields: list[Optional[str]] = [] # 每列对应的 field_path（完整）
        self._visible_headers: list[str] = []          # 列表中实际显示的列标题
        self._visible_fields: list[Optional[str]] = [] # 可见列对应的 field_path
        self._column_ids: list[str] = []              # "col0", "col1", ...
        self._has_template: bool = False

        # ---- 预制信息 ----
        self._prefill_profiles: list[dict] = self._sanitize_prefill(
            self.config.get("prefill_profiles", [])
        )
        self._prefill_var: Optional[tk.StringVar] = None
        self._edit_prefill_btn: Optional[ttk.Button] = None
        self._prefill_echo: Optional[tk.Text] = None
        self._prefill_echo_frame: Optional[ttk.Frame] = None

        # ---- 创建主窗口 ----
        self._root = tk.Tk()
        self._root.title(self._app_title)
        self._root.geometry("960x620")
        self._root.minsize(700, 480)

        # Windows DPI 适配
        if sys.platform == "win32":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
            try:
                icon_path = resource_path("icon.ico")
                if os.path.exists(icon_path):
                    self._root.iconbitmap(icon_path)
            except Exception:
                pass

        self._build_ui()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.bind("<Control-Shift-D>", self._dump_diagnostics)

        # ---- 应用当前模板（表头来自 app_config.json，不读内置模板文件）----
        if not self._has_template:
            self._apply_template_by_key(self._template_key)

        # ---- 恢复已保存数据 ----
        self._restore_saved_data()

        # ---- 启动 ----
        self._running = True
        self._last_clipboard = ""
        logger.info(
            "应用启动完成 | dc_enabled=%s | poll_interval=%dms | dc_interval=%dms | "
            "auto_save=%ds | max_errors/min=%d",
            self._dc_enabled,
            self.config.get("poll_interval_ms", 400),
            int(self._dc_interval * 1000),
            self.config.get("auto_save_interval_s", 120),
            self._max_errors_per_minute,
        )

        # 启动剪贴板轮询
        self._root.after(300, self._poll_clipboard)

        # 启动鼠标采集
        if self._dc_enabled:
            self._start_mouse_capture()

        # 启动自动保存
        if self._auto_save_interval > 0:
            self._schedule_auto_save()

        # 启动健康检查
        self._root.after(10000, self._health_check)

    # ======================== 剪贴板读取 ========================

    def _safe_read_clipboard(self) -> str:
        """读取工作线程的最新剪贴板快照（非阻塞，不调用 WinAPI）。"""
        return self._clipboard_worker.get_latest_text()

    def _poll_clipboard(self) -> None:
        """主线程轮询剪贴板 — 仅处理剪贴板变化 → 预览更新 + 自动转储。"""
        if not self._running:
            return

        t_start = time.time()
        self._last_poll_time = t_start
        self._poll_count += 1

        try:
            text = self._safe_read_clipboard()

            # 剪贴板有新内容 → 更新预览
            if (
                text
                and text.strip()
                and text.strip() != self._last_clipboard.strip()
            ):
                logger.debug("_poll_clipboard: 剪贴板变化 | len=%d", len(text))
                self._last_clipboard = text
                self._set_preview(text)

                # 自动转储（仅微信窗口）
                if not self._degraded and self._auto_var.get():
                    wx_keywords = self.config.get("wechat_keywords", ["微信", "WeChat"])
                    if is_wechat_active(wx_keywords):
                        self._transfer()

            # 降级模式：自动恢复
            if self._degraded and not self._dc_paused:
                self._check_recovery()

            # 心跳日志（每 60 次轮询 ~24 秒）
            if self._poll_count % 60 == 0:
                preview_len = 0
                try:
                    preview_len = len(self._preview_text.get("1.0", tk.END).strip())
                except Exception:
                    pass
                logger.debug(
                    "心跳 | poll=#%d | clip_len=%d | preview=%d | "
                    "dc=%s | auto=%s | degraded=%s | errors=%d | "
                    "poll_latency=%dms",
                    self._poll_count,
                    len(text) if text else 0,
                    preview_len,
                    self._dc_enabled and not self._dc_paused,
                    self._auto_var.get(),
                    self._degraded,
                    len(self._error_timestamps),
                    int((time.time() - t_start) * 1000),
                )

            # 延迟告警
            elapsed_ms = int((time.time() - t_start) * 1000)
            if elapsed_ms > 200:
                logger.warning("_poll_clipboard 延迟过高: %dms", elapsed_ms)

        except Exception as e:
            self._record_error(f"剪贴板轮询异常: {e}")
            try:
                self._last_clipboard = self._safe_read_clipboard()
            except Exception:
                pass
        finally:
            if self._running:
                self._root.after(
                    self.config.get("poll_interval_ms", 400),
                    self._poll_clipboard,
                )

    # ======================== UI 构建 ========================

    def _build_ui(self) -> None:
        pad_x = 14

        # === 顶栏 ===
        header = ttk.Frame(self._root)
        header.pack(fill=tk.X, padx=pad_x, pady=(14, 0))

        ttk.Label(
            header, text=f"📋 {self._app_title}",
            font=("Microsoft YaHei", 14, "bold"),
        ).pack(side=tk.LEFT)

        status_right = ttk.Frame(header)
        status_right.pack(side=tk.RIGHT)

        self._source_var = tk.StringVar(value="")
        ttk.Label(
            status_right, textvariable=self._source_var,
            font=("Microsoft YaHei", 8), foreground="#aaa",
        ).pack(side=tk.RIGHT, padx=(0, 8))

        self._status_var = tk.StringVar(value="🟢 监听中")
        self._status_label = ttk.Label(
            status_right, textvariable=self._status_var,
            foreground="green", font=("Microsoft YaHei", 10),
        )
        self._status_label.pack(side=tk.RIGHT)

        ttk.Separator(self._root, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=pad_x, pady=8
        )

        # === 使用说明 ===
        hint = ttk.Frame(self._root)
        hint.pack(fill=tk.X, padx=pad_x)
        ttk.Label(
            hint,
            text="💡 双击(选词)/三击(选行) → 自动复制+转储 | 或 Ctrl+C → 点「转储」",
            font=("Microsoft YaHei", 8),
            foreground="#999",
        ).pack(anchor=tk.W)

        # === 健康状态条 ===
        self._health_frame = ttk.Frame(self._root)
        # 初始隐藏，有问题时才显示

        self._health_var = tk.StringVar(value="")
        self._health_label = ttk.Label(
            self._health_frame,
            textvariable=self._health_var,
            font=("Microsoft YaHei", 8),
            foreground="#E67E22",
        )
        self._health_label.pack(side=tk.LEFT, padx=pad_x)

        # === 预览区 + 收集区（可拖拽分隔，窗口缩放时按权重分配） ===
        paned = ttk.Panedwindow(self._root, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=pad_x, pady=(8, 2))

        preview_frame = ttk.LabelFrame(paned, text="📋 剪贴板预览（可编辑）", padding=6)

        preview_body = ttk.Frame(preview_frame)
        preview_body.pack(fill=tk.BOTH, expand=True)

        self._preview_text = tk.Text(
            preview_body,
            font=("Microsoft YaHei", 10),
            wrap=tk.WORD,
            height=3,
            state="normal",             # 显式声明可编辑
            insertbackground="#1a1a1a",  # 光标颜色（浅色背景上更醒目）
            bg="#FFFDE7",
            fg="#333333",
            relief=tk.FLAT,
            borderwidth=1,
            highlightbackground="#E0DCC0",
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        preview_vsb = ttk.Scrollbar(
            preview_body, orient=tk.VERTICAL, command=self._preview_text.yview,
        )
        self._preview_text.configure(yscrollcommand=preview_vsb.set)
        preview_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._preview_text.bind("<KeyRelease>", self._on_preview_modified)

        # 预览区按钮行
        preview_btns = ttk.Frame(preview_frame)
        preview_btns.pack(fill=tk.X, pady=(6, 0))

        self._preview_info_var = tk.StringVar(value="等待复制...")
        ttk.Label(
            preview_btns,
            textvariable=self._preview_info_var,
            font=("Microsoft YaHei", 8),
            foreground="#aaa",
        ).pack(side=tk.LEFT)

        self._transfer_btn = ttk.Button(
            preview_btns, text="📥 转储到文本区",
            command=self._transfer,
        )
        self._transfer_btn.pack(side=tk.RIGHT)
        self._transfer_btn.configure(state=tk.DISABLED)

        # 连击复制转储开关
        self._dc_var = tk.BooleanVar(value=self.config.get("double_click_copy", True))
        self._dc_cb = ttk.Checkbutton(
            preview_btns, text="🖱 连击复制", variable=self._dc_var,
            command=self._toggle_double_click,
        )
        self._dc_cb.pack(side=tk.RIGHT, padx=(0, 10))

        # 自动转储开关
        self._auto_var = tk.BooleanVar(
            value=self.config.get("auto_transfer", False)
        )
        self._auto_cb = ttk.Checkbutton(
            preview_btns, text="自动转储", variable=self._auto_var,
            command=self._toggle_auto,
        )
        self._auto_cb.pack(side=tk.RIGHT, padx=(0, 12))

        # 启动恢复上次数据开关
        self._restore_var = tk.BooleanVar(
            value=self.config.get("auto_restore_data", True)
        )
        self._restore_cb = ttk.Checkbutton(
            preview_btns, text="💾 启动恢复上次数据", variable=self._restore_var,
            command=self._toggle_restore,
        )
        self._restore_cb.pack(side=tk.RIGHT, padx=(0, 12))

        paned.add(preview_frame, weight=3)

        # === 收集区 ===
        self._count_var = tk.StringVar(value="已收集: 0 条")

        collect_frame = ttk.LabelFrame(paned, text="📦 已收集文本", padding=6)

        # 表格工具栏
        collect_toolbar = ttk.Frame(collect_frame)
        collect_toolbar.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(
            collect_toolbar,
            textvariable=self._count_var,
            font=("Microsoft YaHei", 9),
            foreground="#666",
        ).pack(side=tk.LEFT)

        # 模版下拉框（JD官网/SF 暂未开放，置灰不可选）
        self._template_var = tk.StringVar(value=self._template_label(self._template_key))
        template_labels = [o.get("label", o.get("key", "")) for o in self._template_options]
        self._template_menu = tk.OptionMenu(
            collect_toolbar, self._template_var, *template_labels,
            command=self._on_template_selected,
        )
        self._template_menu.config(width=14)
        self._template_menu.pack(side=tk.LEFT, padx=(8, 0))
        for opt in self._template_options:
            if not opt.get("enabled"):
                self._template_menu["menu"].entryconfigure(
                    opt.get("label", opt.get("key", "")), state="disabled"
                )

        self._edit_prefill_btn = ttk.Button(
            collect_toolbar, text="✏️ 编辑预制信息",
            command=self._edit_prefill,
        )
        self._edit_prefill_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._define_fields_btn = ttk.Button(
            collect_toolbar, text="📋 定义配置字段",
            command=self._define_export_fields,
        )
        self._define_fields_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._prefill_var = tk.StringVar(value="预制信息: 未导入")
        ttk.Label(
            collect_toolbar, textvariable=self._prefill_var,
            font=("Microsoft YaHei", 8), foreground="#888",
        ).pack(side=tk.LEFT, padx=(10, 0))

        # 撤销清空按钮
        self._undo_btn = ttk.Button(
            collect_toolbar, text="↩ 撤销清空",
            command=self._undo_clear,
        )
        self._undo_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._undo_btn.configure(state=tk.DISABLED)

        ttk.Button(
            collect_toolbar, text="🗑 删除选中",
            command=self._delete_selected_rows,
        ).pack(side=tk.RIGHT, padx=(0, 6))

        ttk.Button(
            collect_toolbar, text="🗑 清空收集区",
            command=self._clear_all,
        ).pack(side=tk.RIGHT)

        # === 预制信息回显区（只读，带滚动条，由 _refresh_prefill_echo 控制显示）===
        self._prefill_echo_frame = ttk.Frame(collect_frame)
        self._prefill_echo = tk.Text(
            self._prefill_echo_frame,
            font=("Microsoft YaHei", 9),
            wrap=tk.WORD,
            height=2,
            state="disabled",
            bg="#F3F6FB",
            fg="#333333",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#D5DDE8",
            padx=8,
            pady=6,
        )
        echo_vsb = ttk.Scrollbar(
            self._prefill_echo_frame, orient=tk.VERTICAL,
            command=self._prefill_echo.yview,
        )
        self._prefill_echo.configure(yscrollcommand=echo_vsb.set)
        echo_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._prefill_echo.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # 不在此处 pack echo_frame；由 _refresh_prefill_echo 按需显示/隐藏

        # Treeview + 滚动条容器
        self._collect_tree_container = ttk.Frame(collect_frame)
        self._collect_tree_container.pack(fill=tk.BOTH, expand=True)
        self._collect_tree_container.grid_rowconfigure(0, weight=1)
        self._collect_tree_container.grid_columnconfigure(0, weight=1)

        # 底部统计字段：显示当前已收集行数
        self._stats_var = tk.StringVar(value="已收集行数: 0")
        ttk.Label(
            collect_frame,
            textvariable=self._stats_var,
            font=("Microsoft YaHei", 9),
            foreground="#555",
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(4, 0))

        # 编辑状态
        self._edit_entry: Optional[tk.Entry] = None
        self._edit_item: Optional[str] = None
        self._edit_col: int = -1

        # 初始化表格（默认三列）
        self._setup_collect_table(DEFAULT_HEADERS, self._selected_export_fields or DEFAULT_HEADERS)

        paned.add(collect_frame, weight=4)

        # === 底部按钮 ===
        bottom = ttk.Frame(self._root)
        bottom.pack(fill=tk.X, padx=pad_x, pady=(4, 14))

        ttk.Button(bottom, text="📄 复制全部", command=self._copy_all).pack(
            side=tk.LEFT
        )

        ttk.Button(
            bottom, text="📊 导出Excel", command=self._export_excel,
        ).pack(side=tk.LEFT, padx=(6, 0))

        # 错误计数指示器
        self._error_indicator_var = tk.StringVar(value="")
        ttk.Label(
            bottom, textvariable=self._error_indicator_var,
            font=("Microsoft YaHei", 8), foreground="#ccc",
        ).pack(side=tk.RIGHT)

        # 初始化预制信息状态
        self._update_prefill_status()

    def _update_count_display(self) -> None:
        """同步顶部计数与底部统计字段（当前已收集行数）。"""
        self._count_var.set(f"已收集: {self._capture_count} 条")
        self._stats_var.set(f"已收集行数: {self._capture_count}")

    # ======================== 动态列管理 ========================

    def _setup_collect_table(self, headers: list[str], visible_headers: Optional[list[str]] = None) -> None:
        """根据 headers 构建 Treeview 表格。

        visible_headers 为用户在「定义配置字段」中勾选的导出字段（不含分类），
        未传时使用完整模版表头。
        """
        # 映射表头到字段（完整模版列）
        self._template_headers = headers
        self._mapped_fields = map_headers_to_fields(headers)

        # 可见列：仅展示勾选的导出字段，不展示字段分类
        display_headers = list(visible_headers) if visible_headers is not None else list(headers)
        self._visible_headers = display_headers
        self._visible_fields = map_headers_to_fields(display_headers)
        n_cols = len(self._visible_headers)

        # 生成列 ID 和宽度（数据列 = 序号列 seq + 可见模版列）
        self._column_ids = ["seq"] + [f"col{i}" for i in range(n_cols)]
        col_widths = [compute_column_width(f) for f in self._visible_fields]

        # 清理容器中的旧控件
        for w in self._collect_tree_container.winfo_children():
            w.destroy()

        # 放大表格字体（含复选框 glyph），行高由 rowheight 决定，不受影响
        _style = ttk.Style()
        _style.configure("Treeview", font=("Microsoft YaHei", 10))

        # 创建 Treeview
        self._collect_table = ttk.Treeview(
            self._collect_tree_container,
            columns=self._column_ids,
            show="tree headings",
            selectmode="extended",
            height=6,
        )

        # 复选框列（#0 树列）：标题位放置全选框，行内显示 ☐/☑，不参与数据列
        self._collect_table.heading("#0", text="☐")
        self._collect_table.column(
            "#0", width=44, minwidth=40, anchor=tk.CENTER, stretch=False,
        )

        # 序号列
        self._collect_table.heading("seq", text="序号")
        self._collect_table.column(
            "seq", width=52, minwidth=40, anchor=tk.CENTER, stretch=False,
        )

        # 低置信度行高亮标签
        self._collect_table.tag_configure(
            "low_confidence", background="#FFF3CD",
        )

        for col_id, header, width in zip(
            self._column_ids[1:], self._visible_headers, col_widths
        ):
            self._collect_table.heading(col_id, text=header)
            anchor = tk.W if width >= 200 else tk.CENTER
            self._collect_table.column(
                col_id, width=width, minwidth=40, anchor=anchor,
            )

        # 滚动条
        collect_vsb = ttk.Scrollbar(
            self._collect_tree_container, orient=tk.VERTICAL,
            command=self._collect_table.yview,
        )
        collect_hsb = ttk.Scrollbar(
            self._collect_tree_container, orient=tk.HORIZONTAL,
            command=self._collect_table.xview,
        )
        self._collect_table.configure(
            yscrollcommand=collect_vsb.set, xscrollcommand=collect_hsb.set,
        )

        self._collect_table.grid(row=0, column=0, sticky="nsew")
        collect_vsb.grid(row=0, column=1, sticky="ns")
        collect_hsb.grid(row=1, column=0, sticky="ew")

        # 事件绑定
        self._collect_table.bind("<Button-3>", self._on_collect_table_right_click)
        self._collect_table.bind("<Double-1>", self._on_collect_table_double_click_edit)
        self._collect_table.bind("<Button-1>", self._on_collect_table_single_click)
        self._collect_table.bind("<<TreeviewSelect>>", self._on_select_changed)

        # 恢复编辑状态
        self._edit_entry = None
        self._edit_item = None
        self._edit_col = -1

    def _reconfigure_columns(self, new_headers: list[str]) -> None:
        """切换模版：保存旧数据 → 重建表格 → 迁移数据。"""
        # 完成正在进行的编辑
        self._finish_edit(save=True)

        # 备份旧数据
        old_data = self._row_data[:]

        # 重建表格
        self._setup_collect_table(new_headers, self._selected_export_fields or new_headers)

        # 重新填充数据
        self._row_data = []
        for data in old_data:
            fields = data.get("fields", {})
            self._insert_restored_row(data, fields)

        # 更新计数
        self._capture_count = len(self._row_data)
        self._update_count_display()
        self._dirty = True

    def _template_label(self, key: str) -> str:
        """根据模板 key 返回下拉框显示名。"""
        for opt in self._template_options:
            if opt.get("key") == key:
                return opt.get("label", key)
        return key

    def _on_template_selected(self, value: str) -> None:
        """模板下拉框选择处理；未开放的模板保持默认并提示。"""
        option = next(
            (o for o in self._template_options if o.get("label") == value), None
        )
        if not option or not option.get("enabled"):
            self._template_var.set(self._template_label(self._template_key))
            messagebox.showinfo("暂未开放", "该模板暂未开放，当前仅支持 JD下单模板。")
            return
        self._template_key = option["key"]
        if self._apply_template_by_key(self._template_key):
            self._selected_export_fields = self._load_export_field_selection()
            self._reconfigure_columns(self._template_headers)
            save_config(self.config)
            self._flash_status(f"✅ 已切换到 {value}")

    def _apply_template_by_key(self, key: str) -> bool:
        """根据模板类型从 app_config.json 获取表头并应用到表格。"""
        template_cfg = self.app_config.get("template_configs", {}).get(key, {})
        headers = [
            field
            for cat in template_cfg.get("categories", [])
            for field in cat.get("fields", [])
        ]
        if not headers:
            logger.warning("模板 %s 尚未配置字段，跳过应用", key)
            return False
        self._reconfigure_columns(headers)
        self._has_template = True
        logger.info("已应用模板 %s | %d 列（来自 app_config.json）", key, len(headers))
        return True

    def _available_export_fields(self) -> list:
        """返回当前模板配置中全部可导出字段。"""
        cfg = self.app_config.get("template_configs", {}).get(self._template_key, {})
        return [
            field
            for cat in cfg.get("categories", [])
            for field in cat.get("fields", [])
        ]

    def _load_export_field_selection(self) -> list:
        """读取用户保存的导出字段选择；无保存时默认全选。"""
        available = self._available_export_fields()
        saved = self.config.get("export_field_selection") or []
        if saved:
            return [f for f in available if f in saved]
        return list(available)

    def _selected_export_categories(self) -> list:
        """按用户勾选结果过滤分类字段，返回 [(分类, [字段...]), ...]。"""
        cats = self.app_config.get("template_configs", {}).get(self._template_key, {}).get("categories", [])
        result = []
        for cat in cats:
            fields = [f for f in cat.get("fields", []) if f in self._selected_export_fields]
            if fields:
                result.append((cat.get("name", ""), fields))
        return result

    def _define_export_fields(self) -> None:
        """打开「定义配置字段」对话框，按分类勾选导出字段。"""
        categories = self.app_config.get("template_configs", {}).get(self._template_key, {}).get("categories", [])
        if not categories:
            messagebox.showinfo("提示", "当前模板暂未配置可导出字段")
            return

        dialog = tk.Toplevel(self._root)
        dialog.title("定义配置字段")
        dialog.transient(self._root)
        dialog.grab_set()
        dialog.geometry("760x600")

        container = ttk.Frame(dialog)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        vars_by_field: dict[str, tk.BooleanVar] = {}
        for cat in categories:
            cat_name = cat.get("name", "")
            fields = cat.get("fields", [])
            if not fields:
                continue
            ttk.Label(
                inner, text=cat_name,
                font=("Microsoft YaHei", 10, "bold"),
            ).pack(anchor="w", pady=(8, 2))
            frame = ttk.Frame(inner)
            frame.pack(fill=tk.X)
            for i, field in enumerate(fields):
                var = tk.BooleanVar(value=field in self._selected_export_fields)
                vars_by_field[field] = var
                ttk.Checkbutton(frame, text=field, variable=var).grid(
                    row=i // 3, column=i % 3, sticky="w", padx=8, pady=2,
                )

        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill=tk.X, padx=10, pady=(0, 10))

        def select_all():
            for var in vars_by_field.values():
                var.set(True)

        def select_none():
            for var in vars_by_field.values():
                var.set(False)

        def confirm():
            self._selected_export_fields = [
                f for f, var in vars_by_field.items() if var.get()
            ]
            self.config["export_field_selection"] = self._selected_export_fields
            save_config(self.config)
            self._reconfigure_columns(self._template_headers)
            dialog.destroy()
            self._flash_status(
                f"📋 已保存 {len(self._selected_export_fields)} 个导出字段"
            )

        ttk.Button(btn_row, text="全选", command=select_all).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="全不选", command=select_none).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(btn_row, text="确定", command=confirm).pack(side=tk.RIGHT)
        ttk.Button(
            btn_row, text="取消", command=dialog.destroy,
        ).pack(side=tk.RIGHT, padx=(0, 6))

    # ======================== 预制信息 ========================

    @staticmethod
    def _sanitize_prefill(profiles) -> list[dict]:
        """清洗从配置加载的预制信息，保证结构一致。"""
        out: list[dict] = []
        for p in profiles or []:
            if not isinstance(p, dict):
                continue
            values = p.get("values") or {}
            if not isinstance(values, dict):
                values = {}
            cleaned: dict = {}
            for k, v in values.items():
                s = str(v).strip()
                # 去掉 Excel 数值单元格遗留的 ".0"（15811111111.0 → 15811111111）
                if s.endswith(".0") and s[:-2].isdigit():
                    s = s[:-2]
                cleaned[str(k)] = s
            out.append({
                "enabled": bool(p.get("enabled", False)),
                "label": str(p.get("label", "")),
                "values": cleaned,
            })
        return out

    @staticmethod
    def _derive_prefill_label(values: dict, index: int) -> str:
        """从档案的关键字段推导一个简短标签，便于区分两个档案。"""
        priority = [
            "发货仓编码", "寄件人地址", "发货地址", "寄件地址",
            "物品类型", "托寄物", "寄件人姓名", "商品", "时效产品",
        ]
        for key in priority:
            v = (values or {}).get(key, "").strip()
            if v:
                return v[:12]
        return f"档案{index + 1}"

    def _prefill_headers(self) -> list[str]:
        """返回当前预制信息档案的字段名（按出现顺序去重）。"""
        headers: list[str] = []
        for p in self._prefill_profiles:
            for h in p.get("values", {}):
                if h not in headers:
                    headers.append(h)
        return headers

    def _open_prefill_dialog(self, headers: list[str], profiles: list[dict]):
        """打开预制信息确认子窗口（单一预制信息，无档案勾选）。

        仅展示 PREFILL_FIELDS 六个字段；返回确认后的 profiles 或 None（取消）。
        """
        display_headers = list(PREFILL_FIELDS)
        values = self._single_prefill_values(profiles)

        top = tk.Toplevel(self._root)
        top.title("预制信息确认")
        top.transient(self._root)
        top.resizable(False, False)

        pad = 12
        ttk.Label(
            top,
            text="核对/编辑预制信息，点击「确认」后应用到导出。",
            font=("Microsoft YaHei", 9), foreground="#666",
        ).pack(anchor=tk.W, padx=pad, pady=(pad, 6))

        body = ttk.Frame(top)
        body.pack(fill=tk.BOTH, expand=True, padx=pad, pady=4)

        value_vars = {
            h: tk.StringVar(value=values.get(h, "")) for h in display_headers
        }
        for i, h in enumerate(display_headers):
            ttk.Label(body, text=h).grid(
                row=i, column=0, sticky="w", padx=4, pady=2)
            ttk.Entry(body, textvariable=value_vars[h], width=40).grid(
                row=i, column=1, sticky="ew", padx=4, pady=2)
        body.grid_columnconfigure(1, weight=1)

        result: dict = {"profiles": None}

        def on_confirm():
            vals = {h: value_vars[h].get().strip() for h in display_headers}
            missing = self._validate_prefill(vals)
            if missing:
                messagebox.showwarning(
                    "必填项缺失",
                    "以下字段未填写，请补充后再确认：\n\n" + "\n".join(missing),
                    parent=top,
                )
                return
            result["profiles"] = [{
                "enabled": True,
                "label": "",
                "values": vals,
            }]
            top.destroy()

        def on_reset():
            if not messagebox.askyesno(
                "确认重置", "确定要清空当前填写的预制信息吗？", parent=top
            ):
                return
            for var in value_vars.values():
                var.set("")

        def on_cancel():
            result["profiles"] = None
            top.destroy()

        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, padx=pad, pady=(6, pad))
        ttk.Button(btns, text="重置", command=on_reset).pack(side=tk.LEFT)
        ttk.Button(btns, text="确认", command=on_confirm).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="取消", command=on_cancel).pack(side=tk.RIGHT)

        # 设定窗口尺寸并居中
        top.update_idletasks()
        req_w = max(460, top.winfo_reqwidth())
        body_h = body.winfo_reqheight()
        req_h = min(420, max(280, body_h + 130))
        x = self._root.winfo_x() + (self._root.winfo_width() - req_w) // 2
        y = self._root.winfo_y() + (self._root.winfo_height() - req_h) // 2
        top.geometry(f"{req_w}x{req_h}+{max(0, x)}+{max(0, y)}")

        # 窗口可见后再抢焦点（避免部分平台 grab 报错）
        try:
            top.wait_visibility()
            top.grab_set()
        except tk.TclError:
            pass

        top.wait_window()
        return result["profiles"]

    def _edit_prefill(self) -> None:
        """打开预制信息确认子窗口（不重新导入文件）。

        无预制信息时基于 PREFILL_FIELDS 新建空白表单供手动填写。
        """
        profiles = self._prefill_profiles or [{
            "enabled": True,
            "label": "",
            "values": {},
        }]
        confirmed = self._open_prefill_dialog(PREFILL_FIELDS, profiles)
        if confirmed is None:
            return
        self._prefill_profiles = self._sanitize_prefill(confirmed)
        self.config["prefill_profiles"] = self._prefill_profiles
        save_config(self.config)
        self._update_prefill_status()
        self._flash_status("✅ 预制信息已更新")

    def _update_prefill_status(self) -> None:
        """刷新预制信息状态标签、编辑按钮与回显区。"""
        if not hasattr(self, "_prefill_var") or self._prefill_var is None:
            return
        # 编辑按钮始终可用：无预制信息时也允许点击填写
        if self._edit_prefill_btn is not None:
            self._edit_prefill_btn.configure(state=tk.NORMAL)
        if not self._prefill_profiles:
            self._prefill_var.set("预制信息: 未导入")
        else:
            self._prefill_var.set("预制信息: 已配置")
        self._refresh_prefill_echo()

    def _refresh_prefill_echo(self) -> None:
        """把已确认的预制信息回显到「已收集文本」区域上方的只读框。"""
        if self._prefill_echo is None or self._prefill_echo_frame is None:
            return

        if not self._prefill_profiles:
            self._prefill_echo.configure(state="normal")
            self._prefill_echo.delete("1.0", tk.END)
            self._prefill_echo.configure(state="disabled")
            self._prefill_echo_frame.pack_forget()
            return

        values = self._prefill_profiles[0].get("values") or {}
        fields = [
            f"{k}：{v}"
            for k, v in values.items()
            if str(v).strip()
        ]
        lines = ["【预制信息】" + "｜".join(fields)] if fields else ["【预制信息】未填写"]

        self._prefill_echo.configure(state="normal")
        self._prefill_echo.delete("1.0", tk.END)
        self._prefill_echo.insert("1.0", "\n".join(lines))
        self._prefill_echo.configure(state="disabled")

        # 自适应高度（上限 5 行，超出用滚动条滚动）
        self._prefill_echo.configure(height=min(5, max(2, len(lines))))

        if not self._prefill_echo_frame.winfo_ismapped():
            self._prefill_echo_frame.pack(
                fill=tk.X, pady=(0, 4), before=self._collect_tree_container
            )

    def _merge_prefill(self, rows: list[list], headers: Optional[list[str]] = None) -> list[list]:
        """把已启用的预制信息合并到导出行（仅填充留空列，后勾选档案覆盖前者）。"""
        if headers is None:
            headers = self._template_headers
        enabled = [p for p in self._prefill_profiles if p.get("enabled")]
        if not enabled or not headers:
            return rows

        # 对每一列，取「最后一个启用档案」提供的非空值
        prefill_by_col: dict[int, str] = {}
        for col_idx, header in enumerate(headers):
            for p in enabled:
                v = (p.get("values") or {}).get(header, "")
                if v:
                    prefill_by_col[col_idx] = v

        if not prefill_by_col:
            return rows

        merged: list[list] = []
        for row in rows:
            new_row = list(row)
            for col_idx, v in prefill_by_col.items():
                while len(new_row) <= col_idx:
                    new_row.append("")
                if not str(new_row[col_idx]).strip():
                    new_row[col_idx] = v
            merged.append(new_row)
        return merged

    # ======================== 预览区操作 ========================

    def _set_preview(self, text: str) -> None:
        """更新预览区内容。"""
        try:
            self._preview_text.delete("1.0", tk.END)
            self._preview_text.insert("1.0", text)

            self._preview_info_var.set(f"{len(text)} 字符")
            self._transfer_btn.configure(state=tk.NORMAL)

            source = get_foreground_title()
            if source:
                short = source[:30] + ("..." if len(source) > 30 else "")
                self._source_var.set(f"来源: {short}")
            else:
                self._source_var.set("")
        except Exception as e:
            logger.warning("预览区更新失败: %s", e)

    def _on_preview_modified(self, event=None) -> None:
        """预览区内容被用户手动编辑时：刷新字符计数与转储按钮状态。"""
        try:
            text = self._preview_text.get("1.0", tk.END).strip()
            if text:
                self._preview_info_var.set(f"{len(text)} 字符")
                self._transfer_btn.configure(state=tk.NORMAL)
            else:
                self._preview_info_var.set("等待复制...")
                self._transfer_btn.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _clear_preview(self) -> None:
        """清空预览区。"""
        import inspect
        caller = inspect.currentframe().f_back
        caller_name = caller.f_code.co_name if caller else "?"
        logger.debug("_clear_preview 被 %s() 调用", caller_name)
        try:
            self._preview_text.delete("1.0", tk.END)
            self._preview_info_var.set("等待复制...")
            self._transfer_btn.configure(state=tk.DISABLED)
            self._source_var.set("")
        except Exception:
            pass

    # ======================== 转储 ========================

    def _transfer(self, text: str = None) -> None:
        """将文本转储到收集区——支持多行按行拆分后分别解析。

        若预览区包含多行文本，按行拆分，每行作为一个独立订单解析，
        分别进行地址格式解析后放入已收集文本区域。
        Args:
            text: 要转储的文本，若为 None 则从预览区读取
        """
        if text is None:
            try:
                text = self._preview_text.get("1.0", tk.END).strip()
            except Exception:
                logger.debug("_transfer: 无法读取预览文本")
                return
        if not text:
            logger.debug("_transfer: 文本为空，跳过")
            return

        logger.debug("_transfer: 调用中 | text_len=%d", len(text))

        # 按行拆分，过滤空行
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            logger.debug("_transfer: 拆分后无有效行")
            return

        inserted = 0
        skipped = 0
        low_conf: list[list[str]] = []  # 低置信度行的警告列表
        for line in lines:
            try:
                ok, warnings_list, overall = self._transfer_line(line)
                if ok:
                    inserted += 1
                    if warnings_list:
                        low_conf.append(warnings_list)
                else:
                    skipped += 1
            except Exception as e:
                self._record_error(f"转储异常(单行): {e}")

        # 转储后清空预览
        self._clear_preview()
        self._last_clipboard = text

        if inserted > 0:
            if skipped > 0:
                self._flash_status(f"✅ 已转储 {inserted} 条（跳过 {skipped} 条重复）")
            else:
                self._flash_status(f"✅ 已转储 {inserted} 条")
            # 低置信度告警：提示核对高亮行
            if low_conf:
                if len(low_conf) == 1:
                    detail = "、".join(low_conf[0][:3])
                    self._flash_status(f"⚠️ 低置信度: {detail}", duration=5000)
                else:
                    self._flash_status(
                        f"⚠️ {len(low_conf)} 条低置信度记录，请核对黄色高亮行",
                        duration=5000,
                    )
        else:
            self._flash_status("⏭ 无新增记录", duration=2000)

        logger.info(
            "转储完成 | 插入=%d | 跳过=%d | 行数=%d | 累计=%d",
            inserted, skipped, len(lines), self._capture_count,
        )

    def _transfer_line(self, line: str) -> tuple[bool, list[str], float]:
        """解析并插入单行文本。

        Returns:
            (是否成功插入, 警告列表, 总体置信度)
        """
        if not line or not line.strip():
            return False, [], 0.0

        # 1. 解析订单（姓名、电话、地址、商品、备注）
        order = parse_order(line)

        # 2. 深度地址解析
        addr_text = order.address or line
        parsed_addr = parse_address_safe(addr_text)

        # 3. 构建统一 fields dict
        fields = empty_fields_dict()
        fields["name"] = order.name or ""
        fields["phone"] = order.phone or ""
        if order.address:
            fields["full_address"] = order.address
        fields["province"] = parsed_addr.province or ""
        fields["city"] = parsed_addr.city or ""
        fields["district"] = parsed_addr.district or ""
        fields["development_zone"] = parsed_addr.development_zone or ""
        fields["township"] = parsed_addr.township or ""
        fields["road"] = parsed_addr.road or ""
        fields["community"] = parsed_addr.community or ""
        fields["landmark"] = parsed_addr.landmark or ""
        fields["building"] = parsed_addr.building or ""
        fields["unit"] = parsed_addr.unit or ""
        fields["room"] = parsed_addr.room or ""
        if parsed_addr.full_detail:
            fields["full_detail"] = parsed_addr.full_detail
        if parsed_addr.full_address:
            fields["full_address"] = fields["full_address"] or parsed_addr.full_address
        fields["items"] = order.items or []
        fields["notes"] = order.notes or ""
        fields["raw"] = line

        # 4. 置信度评分
        overall, warnings_list, scores = score_fields(fields)

        # 5. 构建显示行并插入（不再去重，重复文本也追加到列表）
        values = build_row_tuple(fields, self._visible_fields)
        seq = str(len(self._row_data) + 1)
        item = self._collect_table.insert("", tk.END, values=(seq, *values))
        self._collect_table.item(item, text="☐")
        if is_low_confidence(overall, scores):
            self._collect_table.item(item, tags=("low_confidence",))
        self._row_data.append({
            "fields": fields,
            "raw": line,
            "confidence": overall,
            "warnings": warnings_list,
            "scores": scores,
        })

        self._capture_count += 1
        self._update_count_display()
        self._dirty = True

        logger.info(
            "转储成功 | #%d | name=%s | phone=%s | addr_len=%d | conf=%.2f",
            self._capture_count, fields["name"], fields["phone"],
            len(fields["full_address"]), overall,
        )
        return True, warnings_list, overall

    def _refresh_row_confidence(self, idx: int, item: str) -> None:
        """重新评分一行并刷新其高亮标签（用于编辑后、恢复数据后）。"""
        try:
            data = self._row_data[idx]
            fields = data["fields"]
            overall, warnings_list, scores = score_fields(fields)
            data["confidence"] = overall
            data["warnings"] = warnings_list
            data["scores"] = scores
            if is_low_confidence(overall, scores):
                self._collect_table.item(item, tags=("low_confidence",))
            else:
                self._collect_table.item(item, tags=())
        except (IndexError, KeyError):
            pass

    def _insert_restored_row(self, data: dict, fields: dict) -> None:
        """恢复/重建表格时插入一行，并按置信度刷新高亮。"""
        values = build_row_tuple(fields, self._visible_fields)
        seq = str(len(self._row_data) + 1)
        item = self._collect_table.insert("", tk.END, values=(seq, *values))
        self._collect_table.item(item, text="☐")
        self._row_data.append(data)
        self._refresh_row_confidence(len(self._row_data) - 1, item)

    def _toggle_auto(self) -> None:
        self.config["auto_transfer"] = self._auto_var.get()
        save_config(self.config)
        if self._auto_var.get():
            self._flash_status("🔄 自动转储已开启")

    def _toggle_restore(self) -> None:
        """切换启动恢复上次数据开关。"""
        enabled = self._restore_var.get()
        self.config["auto_restore_data"] = enabled
        save_config(self.config)
        if enabled:
            self._flash_status("💾 已开启：启动时自动恢复上次数据")
        else:
            self._flash_status("已关闭：启动时不再恢复上次数据")

    # ======================== 全局连击复制 ========================

    def _start_mouse_capture(self) -> None:
        """启动连击采集：优先 WH_MOUSE_LL 钩子，失败则回退到轮询。"""
        self._dc_enabled = True
        self._mouse_was_down = False
        self._dc_click_count = 0
        if self._try_start_hook():
            logger.info("连击采集已启动 | 方式=WH_MOUSE_LL 钩子")
        else:
            logger.info("连击采集已启动 | 方式=GetAsyncKeyState 轮询（回退）")
            self._start_mouse_poll()

    def _try_start_hook(self) -> bool:
        """尝试安装全局低级鼠标钩子，成功返回 True。"""
        if self._mouse_hook is not None:
            return self._hook_active
        try:
            self._mouse_hook = MouseHook()
            if self._mouse_hook.start():
                self._hook_active = True
                self._schedule_hook_drain()
                return True
            logger.warning("WH_MOUSE_LL 钩子安装失败，回退到轮询")
            self._mouse_hook = None
            return False
        except Exception as e:
            logger.warning("WH_MOUSE_LL 钩子异常(%s)，回退到轮询", e)
            self._mouse_hook = None
            return False

    def _schedule_hook_drain(self) -> None:
        """调度下一次钩子队列消费。"""
        if self._running and self._hook_active:
            self._mouse_hook_id = self._root.after(10, self._drain_mouse_hook)

    def _drain_mouse_hook(self) -> None:
        """从钩子队列取出点击事件，喂给连击判定（主线程）。"""
        self._mouse_hook_id = None
        if not (self._running and self._hook_active
                and self._dc_enabled and not self._dc_paused):
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
            self._record_error(f"鼠标钩子处理异常: {e}")
        finally:
            if self._running and self._hook_active:
                self._schedule_hook_drain()

    def _start_mouse_poll(self) -> None:
        """开始鼠标左键轮询（回退路径，~50Hz）。"""
        self._dc_enabled = True
        self._mouse_was_down = False
        self._dc_click_count = 0
        self._dc_poll_id = self._root.after(20, self._poll_mouse)
        logger.debug("鼠标轮询启动")

    def _stop_mouse_poll(self) -> None:
        """停止连击采集（钩子 + 轮询）。"""
        self._dc_enabled = False

        # 停止钩子
        if self._mouse_hook is not None:
            try:
                self._mouse_hook.stop()
            except Exception:
                pass
            self._mouse_hook = None
        self._hook_active = False
        if self._mouse_hook_id is not None:
            try:
                self._root.after_cancel(self._mouse_hook_id)
            except Exception:
                pass
            self._mouse_hook_id = None

        # 停止轮询
        if self._dc_poll_id:
            self._root.after_cancel(self._dc_poll_id)
            self._dc_poll_id = None
        if self._dc_fire_id is not None:
            try:
                self._root.after_cancel(self._dc_fire_id)
            except Exception:
                pass
            self._dc_fire_id = None
        self._dc_click_count = 0
        logger.debug("连击采集停止")

    def _poll_mouse(self) -> None:
        """轮询鼠标左键状态（回退路径）。"""
        if not self._running:
            return
        if not self._dc_enabled or self._dc_paused:
            self._dc_poll_id = None
            return

        try:
            state = user32.GetAsyncKeyState(VK_LBUTTON)
            is_down = (state & 0x8000) != 0

            if is_down and not self._mouse_was_down:
                self._mouse_was_down = True
                pt = w.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                self._on_mouse_down(pt.x, pt.y, time.time())
            elif not is_down:
                self._mouse_was_down = False
        except Exception as e:
            self._record_error(f"鼠标轮询异常: {e}")
        finally:
            if self._running and self._dc_enabled and not self._dc_paused:
                self._dc_poll_id = self._root.after(20, self._poll_mouse)
            else:
                self._dc_poll_id = None

    def _on_mouse_down(self, x: int, y: int, now: float) -> None:
        """处理一次左键按下事件（钩子与轮询共用），识别连击序列。"""
        # 跳过自身窗口内的点击
        try:
            my_hwnd = int(self._root.frame(), 16)
        except Exception:
            my_hwnd = None
        fg = user32.GetForegroundWindow()
        in_self = bool(my_hwnd and fg == my_hwnd)
        if in_self:
            return

        time_diff = now - self._mouse_last_click
        pos_diff_x = abs(x - self._mouse_last_x)
        pos_diff_y = abs(y - self._mouse_last_y)

        same_burst = (
            self._dc_click_count > 0
            and 0 < time_diff < self._dc_interval
            and pos_diff_x < self._dc_pos_tolerance
            and pos_diff_y < self._dc_pos_tolerance
        )

        if same_burst:
            self._dc_click_count += 1
        else:
            self._dc_click_count = 1

        # 达到双击及以上 → 延迟触发，等待可能到来的第 3 次点击。
        # 双击=选词、三击=选行，延迟可避免在选词阶段就抢跑复制。
        if self._dc_click_count >= 2:
            logger.debug(
                "连击序列检测 | 第%d击 | pos=(%d,%d) | dt=%.0fms",
                self._dc_click_count, x, y, time_diff * 1000,
            )
            self._schedule_dc_fire()

        self._mouse_last_click = now
        self._mouse_last_x = x
        self._mouse_last_y = y

    def _schedule_dc_fire(self) -> None:
        """（重新）调度连击触发，等待点击序列稳定后再执行一次。"""
        if self._dc_fire_id is not None:
            try:
                self._root.after_cancel(self._dc_fire_id)
            except Exception:
                pass
        self._dc_fire_id = self._root.after(self._dc_settle_ms, self._dc_fire)

    def _dc_fire(self) -> None:
        """连击序列稳定后触发：Ctrl+C → 等待剪贴板 → 转储（仅执行一次）。"""
        self._dc_fire_id = None
        if not self._running or not self._dc_enabled or self._dc_paused:
            return

        now = time.time()
        # 冷却检查：防止上一次触发后立即再次误触发
        if now < self._dc_cooldown_until:
            self._dc_click_count = 0
            return

        logger.debug("连击稳定触发 | 点击次数=%d | pos=(%d,%d)",
                     self._dc_click_count, self._mouse_last_x, self._mouse_last_y)

        # 记录连击历史（保留最近 20 条）
        self._dc_history.append((now, self._mouse_last_x, self._mouse_last_y))
        if len(self._dc_history) > 20:
            self._dc_history = self._dc_history[-20:]

        # 设置冷却（800ms）
        self._dc_cooldown_until = now + self._dc_cooldown_s
        self._dc_click_count = 0

        # === 直接链路：Ctrl+C → 等待剪贴板 → 转储（带自校验与重试）===
        prev_clip = self._last_clipboard
        new_text = self._capture_with_retry(prev_clip)
        if new_text:
            self._last_clipboard = new_text
            self._set_preview(new_text)
            self._transfer(text=new_text)
        else:
            logger.warning(
                "连击采集失败（多次重试后剪贴板仍未变化）| prev_len=%d | fg=%s",
                len(prev_clip), get_foreground_title()[:30],
            )
            self._flash_status(
                "⚠️ 采集失败：未检测到复制内容，请手动 Ctrl+C", duration=6000,
            )

    def _capture_with_retry(self, prev_clip: str, attempts: int = 3):
        """发送 Ctrl+C 并等待剪贴板变化；失败则重试，返回新文本或 None。

        自校验：每次发送后主动轮询剪贴板，确认内容确实发生变化才判定成功。
        最多重试 attempts 次（首次 + attempts-1 次重试），避免静默漏采。
        """
        for i in range(attempts):
            if not send_ctrl_c():
                logger.warning("连击后 Ctrl+C 发送失败（第%d/%d次）", i + 1, attempts)
            else:
                new_text = self._clipboard_worker.wait_for_change(
                    prev_clip, timeout_ms=500, poll_interval_ms=50,
                )
                if new_text:
                    logger.debug(
                        "连击采集成功 | 第%d次尝试 | len=%d",
                        i + 1, len(new_text),
                    )
                    return new_text
            # 重试前短暂等待，避免连续抢发
            time.sleep(0.15)
        return None

    def _toggle_double_click(self) -> None:
        """切换全局连击复制开关。"""
        enabled = self._dc_var.get()
        self.config["double_click_copy"] = enabled
        save_config(self.config)
        if enabled:
            self._dc_paused = False
            self._start_mouse_capture()
            self._flash_status("🖱 连击复制已开启")
            logger.info("连击复制已开启")
        else:
            self._stop_mouse_poll()
            self._flash_status("⏸ 连击复制已关闭")
            logger.info("连击复制已关闭")

    # ======================== 收集区操作 ========================

    def _clear_all(self) -> None:
        """清空收集表格（带撤销支持）。"""
        children = self._collect_table.get_children()
        if not children:
            return

        if messagebox.askyesno(
            "确认清空",
            f"确定要清空所有 {self._capture_count} 条已收集的记录吗？\n\n"
            "清空后可通过「撤销清空」按钮恢复。",
        ):
            # 备份数据用于撤销
            self._undo_data = self._row_data[:]

            for item in children:
                self._collect_table.delete(item)

            self._row_data = []
            self._capture_count = 0
            self._update_count_display()
            self._undo_btn.configure(state=tk.NORMAL)
            self._dirty = True
            logger.info("收集区已清空 | %d 条备份可撤销", len(self._undo_data))

    def _undo_clear(self) -> None:
        """撤销清空操作。"""
        if not hasattr(self, "_undo_data") or not self._undo_data:
            return

        self._row_data = []
        for data in self._undo_data:
            fields = data.get("fields", {})
            self._insert_restored_row(data, fields)

        count = len(self._undo_data)
        self._capture_count = count
        self._update_count_display()
        self._undo_btn.configure(state=tk.DISABLED)
        self._undo_data = []
        self._dirty = True
        self._flash_status(f"↩ 已恢复 {count} 条记录")
        logger.info("撤销清空 | 恢复 %d 条", count)

    def _copy_all(self) -> None:
        """复制收集表格全部内容到剪贴板。"""
        rows = []
        for item in self._collect_table.get_children():
            values = self._collect_table.item(item, "values")
            # 跳过首列序号
            rows.append("\t".join(str(v) for v in values[1:]))
        if rows:
            text = "\n".join(rows)
            if self._clipboard_worker.write_clipboard(text, timeout_ms=2000):
                self._flash_status(f"📋 已复制全部 {len(rows)} 条记录到剪贴板")
            else:
                show_error_dialog(
                    "复制失败",
                    "无法写入剪贴板，请重试。\n如果问题持续，请检查是否有其他程序锁定了剪贴板。",
                )
        else:
            messagebox.showinfo("提示", "收集区为空")

    def _export_excel(self) -> None:
        """按用户定义配置字段导出双行表头 Excel。"""
        if not self._row_data:
            messagebox.showinfo("提示", "没有数据可导出")
            return

        categories = self._selected_export_categories()
        if not categories:
            messagebox.showinfo("提示", "未选择任何导出字段，请先点击「定义配置字段」进行配置")
            return

        headers = flatten_categories(categories)
        mapped = [EXPORT_FIELD_MAP.get(h) for h in headers]

        rows = []
        for data in self._row_data:
            fields = data.get("fields", {})
            rows.append(list(build_row_tuple(fields, mapped)))

        rows = self._merge_prefill(rows, headers)

        default_name = f"产地快打_导出_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path = filedialog.asksaveasfilename(
            title="导出 Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")],
            initialfile=default_name,
        )
        if not file_path:
            return

        try:
            import openpyxl
        except ImportError:
            messagebox.showerror(
                "缺少依赖",
                "导出 Excel 需要 openpyxl 库。\n\n"
                "请运行以下命令安装:\n"
                "  pip install openpyxl",
            )
            return

        try:
            write_export_excel(file_path, categories, rows)
            self._flash_status(f"✅ 已导出 {len(rows)} 条记录到 Excel")
            logger.info(
                "Excel 导出完成 | %s | %d 条记录 | %d 列",
                file_path, len(rows), len(headers),
            )
        except PermissionError:
            show_error_dialog(
                "保存失败",
                "无法写入文件，请检查:\n"
                "  1. 文件是否已在 Excel 中打开\n"
                "  2. 是否有写入权限",
            )
        except Exception as e:
            logger.exception("Excel 导出失败: %s", e)
            show_error_dialog(
                "导出失败",
                f"导出 Excel 时发生错误:\n{str(e)}",
            )

    # ======================== 收集表格交互 ========================

    def _on_collect_table_right_click(self, event) -> None:
        """收集表格右键菜单。"""
        item = self._collect_table.identify_row(event.y)
        if not item:
            return
        # 若右键行不在当前选中集合中，则单独选中它；否则保留多选以便批量删除
        if item not in self._collect_table.selection():
            self._collect_table.selection_set(item)

        # 识别右键所在的列
        clicked_col = self._collect_table.identify_column(event.x)

        menu = tk.Menu(self._root, tearoff=0)
        menu.add_command(
            label="📋 复制整行",
            command=lambda: self._copy_collect_row(item),
        )
        menu.add_separator()

        # 动态生成列映射（#1 为序号列，#2 起为可见列）
        col_map = {}
        for i, header in enumerate(self._visible_headers):
            col_map[f"#{i + 2}"] = header
        for col_id, label in col_map.items():
            menu.add_command(
                label=f"复制{label}",
                command=lambda c=col_id, i=item: self._copy_collect_cell(i, c),
            )

        menu.add_separator()
        menu.add_command(
            label="✏️ 编辑此格",
            command=lambda c=clicked_col, i=item: self._edit_cell(i, c),
        )
        menu.add_separator()
        sel = self._collect_table.selection()
        delete_label = f"🗑 删除选中({len(sel)}行)" if len(sel) > 1 else "🗑 删除此行"
        menu.add_command(
            label=delete_label,
            command=self._delete_selected_rows,
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_collect_table_double_click_edit(self, event) -> None:
        """双击收集表格单元格 → 进入编辑模式。"""
        # 先完成可能正在进行的编辑
        self._finish_edit(save=True)
        item = self._collect_table.identify_row(event.y)
        col = self._collect_table.identify_column(event.x)
        if item and col:
            self._edit_cell(item, col)

    def _on_collect_table_single_click(self, event) -> None:
        """单击处理：勾选列切换选中；其他位置保存当前编辑。"""
        # 标题位全选框点击
        if self._collect_table.identify_region(event.x, event.y) == "heading":
            if self._collect_table.identify_column(event.x) == "#0":
                self._toggle_select_all()
                return "break"
            return

        col = self._collect_table.identify_column(event.x)

        # 勾选列（#0）点击：切换该行选中状态，不影响其他行
        if col == "#0":
            item = self._collect_table.identify_row(event.y)
            if item:
                if item in self._collect_table.selection():
                    self._collect_table.selection_remove(item)
                else:
                    self._collect_table.selection_add(item)
                self._renumber_rows()
                return "break"

        # 原有：单击表格其他位置 → 保存当前编辑
        if self._edit_entry is not None:
            item = self._collect_table.identify_row(event.y)
            # 如果点击的是正在编辑的同一个单元格，不处理
            if item == self._edit_item and col == f"#{self._edit_col + 1}":
                return
            self._finish_edit(save=True)

    def _edit_cell(self, item: str, col_id: str) -> None:
        """在指定单元格上弹出 Entry 控件进行编辑。"""
        # 先完成之前的编辑
        self._finish_edit(save=True)

        col_index = int(col_id.replace("#", "")) - 1
        if col_index < 0:
            return
        # 序号列不可编辑
        if col_index == 0:
            return

        # 获取单元格的当前值和位置
        values = self._collect_table.item(item, "values")
        if col_index >= len(values):
            return
        current_value = values[col_index]

        bbox = self._collect_table.bbox(item, col_id)
        if not bbox:
            return
        x, y, w_cell, h_cell = bbox

        # 创建 Entry 覆盖在单元格上
        entry = tk.Entry(
            self._collect_table,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT,
            borderwidth=1,
            highlightbackground="#3498DB",
            highlightthickness=2,
            bg="#FFFDE7",
        )
        entry.place(x=x, y=y, width=w_cell, height=h_cell)
        entry.insert(0, current_value)
        entry.select_range(0, tk.END)
        entry.focus_set()

        # 绑定事件
        entry.bind("<Return>", lambda e: self._finish_edit(save=True))
        entry.bind("<Escape>", lambda e: self._finish_edit(save=False))
        entry.bind("<FocusOut>", lambda e: self._finish_edit(save=True))

        self._edit_entry = entry
        self._edit_item = item
        self._edit_col = col_index

    def _finish_edit(self, save: bool = True) -> None:
        """结束编辑，保存或放弃修改。同步 _row_data。"""
        if self._edit_entry is None:
            return

        try:
            if save and self._edit_item and self._edit_col >= 0:
                new_value = self._edit_entry.get()
                values = list(self._collect_table.item(self._edit_item, "values"))
                if self._edit_col < len(values) and values[self._edit_col] != new_value:
                    values[self._edit_col] = new_value
                    self._collect_table.item(self._edit_item, values=tuple(values))
                    self._dirty = True

                    # 同步到 _row_data
                    children = list(self._collect_table.get_children())
                    try:
                        idx = children.index(self._edit_item)
                        if 0 <= idx < len(self._row_data):
                            field_path = (
                                self._visible_fields[self._edit_col - 1]
                                if 0 < self._edit_col <= len(self._visible_fields) else None
                            )
                            if field_path:
                                self._row_data[idx]["fields"][field_path] = new_value
                                # 重新评分并刷新高亮
                                self._refresh_row_confidence(idx, self._edit_item)
                    except (ValueError, IndexError):
                        pass

                    self._flash_status(f"✅ 已修改: {new_value[:20]}{'...' if len(new_value) > 20 else ''}")

            self._edit_entry.destroy()
        except tk.TclError:
            pass
        except Exception as e:
            logger.warning("结束编辑异常: %s", e)
        finally:
            self._edit_entry = None
            self._edit_item = None
            self._edit_col = -1

    def _copy_collect_cell(self, item: str, col_id: str) -> None:
        """复制收集表格单个单元格。"""
        col_index = int(col_id.replace("#", "")) - 1
        values = self._collect_table.item(item, "values")
        if 0 <= col_index < len(values):
            text = values[col_index]
            if text:
                if self._clipboard_worker.write_clipboard(text, timeout_ms=2000):
                    self._flash_status(f"📋 已复制: {text}")
                else:
                    self._flash_status("⚠️ 复制失败，请重试")
            else:
                self._flash_status("⚠️ 该字段为空")

    def _copy_collect_row(self, item: str) -> None:
        """复制收集表格整行。"""
        values = self._collect_table.item(item, "values")
        text = "\t".join(str(v) for v in values[1:])
        if self._clipboard_worker.write_clipboard(text, timeout_ms=2000):
            self._flash_status("📋 已复制整行")
        else:
            self._flash_status("⚠️ 复制失败，请重试")

    def _delete_collect_row(self, item: str) -> None:
        """删除收集表格中一行（保留兼容，单行删除）。"""
        self._delete_rows([item])

    def _delete_selected_rows(self) -> None:
        """删除当前选中的所有行（支持 Ctrl/Shift 多选批量删除）。"""
        selected = self._collect_table.selection()
        if not selected:
            self._flash_status("⚠️ 请先选中要删除的行（可 Ctrl/Shift 多选）")
            return
        self._delete_rows(list(selected))

    def _delete_rows(self, items) -> None:
        """批量删除指定行（items 为 Treeview iid 可迭代对象）。"""
        items = set(items)
        if not items:
            return

        # 单行删除沿用原静默行为；多行删除需确认
        if len(items) > 1:
            if not messagebox.askyesno(
                "确认删除",
                f"确定删除选中的 {len(items)} 条记录吗？",
            ):
                return

        children = self._collect_table.get_children()
        remove_idx = {i for i, it in enumerate(children) if it in items}
        self._row_data = [
            d for i, d in enumerate(self._row_data) if i not in remove_idx
        ]

        for it in items:
            self._collect_table.delete(it)

        self._capture_count = len(self._row_data)
        self._update_count_display()
        self._renumber_rows()
        self._dirty = True
        logger.info("删除 %d 条 | 剩余 %d 条", len(items), self._capture_count)

    def _renumber_rows(self) -> None:
        """刷新复选框列（#0）与序号列（seq）：行号连续 + 勾选状态同步 + 表头全选框同步。"""
        sel = set(self._collect_table.selection())
        children = self._collect_table.get_children()
        for i, item in enumerate(children, start=1):
            mark = "☑" if item in sel else "☐"
            self._collect_table.item(item, text=mark)
            values = list(self._collect_table.item(item, "values"))
            if values:
                values[0] = str(i)
                self._collect_table.item(item, values=tuple(values))

        # 表头全选框：全选时显示 ☑，否则 ☐
        all_sel = "☑" if children and len(sel) == len(children) else "☐"
        self._collect_table.heading("#0", text=all_sel)

    def _toggle_select_all(self) -> None:
        """标题位全选框：全选 / 取消全选。"""
        children = self._collect_table.get_children()
        if not children:
            return
        if len(self._collect_table.selection()) == len(children):
            self._collect_table.selection_remove(children)
        else:
            self._collect_table.selection_set(children)
        self._renumber_rows()

    def _on_select_changed(self, _event=None) -> None:
        """选择变化时刷新复选框显示（支持 Ctrl/Shift 多选同步）。"""
        self._renumber_rows()

    # ======================== 状态与健康监控 ========================

    def _flash_status(self, msg: str, duration: int = 3000) -> None:
        """闪态消息（duration 毫秒后恢复默认状态）。"""
        self._status_var.set(msg)
        # 根据消息类型设置颜色
        if msg.startswith("⚠") or msg.startswith("⏸"):
            self._status_label.configure(foreground="#E67E22")
        elif msg.startswith("❌"):
            self._status_label.configure(foreground="red")
        else:
            self._status_label.configure(foreground="green")
        # 取消上一个待恢复的定时器，避免旧定时器提前覆盖新消息
        if self._status_restore_id is not None:
            try:
                self._root.after_cancel(self._status_restore_id)
            except Exception:
                pass
        self._status_restore_id = self._root.after(duration, self._restore_status)

    def _restore_status(self) -> None:
        """恢复默认状态文本。"""
        self._status_restore_id = None
        if self._degraded:
            self._status_var.set("⚠️ 降级运行")
            self._status_label.configure(foreground="#E67E22")
        elif self._dc_paused:
            self._status_var.set("⏸ 连击已暂停")
            self._status_label.configure(foreground="#E67E22")
        else:
            self._status_var.set("🟢 监听中")
            self._status_label.configure(foreground="green")

    def _record_error(self, msg: str) -> None:
        """记录错误并检查是否需要降级。"""
        self._error_count += 1
        now = time.time()

        # 清理 60 秒前的错误
        self._error_timestamps = [
            t for t in self._error_timestamps if now - t < 60
        ]
        self._error_timestamps.append(now)

        logger.warning("错误 #%d (%d/min): %s",
                       self._error_count,
                       len(self._error_timestamps),
                       msg)

        # 错误率过高 → 降级
        if len(self._error_timestamps) >= self._max_errors_per_minute:
            if not self._degraded:
                self._degraded = True
                self._dc_paused = True
                logger.error(
                    "触发降级模式！错误率=%d/min | 连击复制已暂停，"
                    "基础剪贴板监控继续",
                    len(self._error_timestamps),
                )
                self._show_health_warning(
                    f"⚠️ 错误率过高（{len(self._error_timestamps)}次/分钟）\n"
                    "连击复制功能已暂停以保护稳定性\n"
                    "基础的剪贴板监控和手动转储仍可使用\n"
                    "系统将自动尝试恢复"
                )

        # 更新指示器
        if self._error_count > 0:
            self._error_indicator_var.set(
                f"错误: {self._error_count} | "
                f"频率: {len(self._error_timestamps)}/min"
            )

    def _check_recovery(self) -> None:
        """检查是否可以退出降级模式。"""
        now = time.time()
        recent = [t for t in self._error_timestamps if now - t < 60]

        # 错误率降低到阈值的一半以下 → 恢复
        if len(recent) <= self._max_errors_per_minute // 2:
            self._degraded = False
            self._dc_paused = False
            logger.info("降级模式解除 | 错误率=%d/min", len(recent))
            self._hide_health_warning()
            self._restore_status()

            # 重新启动连击（如果用户启用的话）
            if self._dc_var.get() and not self._hook_active and not self._dc_poll_id:
                self._start_mouse_capture()

    def _health_check(self) -> None:
        """定期健康检查。"""
        if not self._running:
            return

        now = time.time()

        # 检查轮询是否卡死
        if self._last_poll_time > 0 and (now - self._last_poll_time) > 5:
            logger.error(
                "剪贴板轮询疑似卡死！距上次轮询 %.1f 秒",
                now - self._last_poll_time,
            )
            self._show_health_warning(
                "⚠️ 剪贴板轮询疑似卡死\n"
                "请检查系统剪贴板是否异常\n"
                "如持续此状态请重启应用"
            )

        # 检查剪贴板工作线程是否有新快照
        if self._clipboard_worker.is_stale(5.0):
            logger.error(
                "剪贴板工作线程疑似卡死！距上次读取 %.1f 秒",
                now - self._clipboard_worker.get_latest_ts(),
            )
            self._show_health_warning(
                "⚠️ 剪贴板繁忙或工作线程卡住\n"
                "请检查其他程序是否长期占用剪贴板"
            )

        # 检查鼠标采集
        if (
            self._dc_enabled
            and not self._dc_paused
            and not self._hook_active
            and self._dc_poll_id is None
        ):
            logger.warning("鼠标采集意外停止，尝试重启")
            self._start_mouse_capture()

        # 定期错误率清理
        self._error_timestamps = [
            t for t in self._error_timestamps if now - t < 60
        ]

        # 自动恢复
        if self._degraded:
            self._check_recovery()

        # 更新错误指示器
        if self._error_count > 0 and len(self._error_timestamps) == 0:
            self._error_indicator_var.set("")

        # 10 秒一次健康检查
        if self._running:
            self._root.after(10000, self._health_check)

    def _show_health_warning(self, msg: str) -> None:
        """显示健康状态条。"""
        self._health_var.set(msg)
        self._health_frame.pack(
            fill=tk.X, padx=14, pady=(0, 4), before=self._preview_text.master
        )
        self._status_var.set("⚠️ 降级运行")
        self._status_label.configure(foreground="#E67E22")

    def _hide_health_warning(self) -> None:
        """隐藏健康状态条。"""
        self._health_frame.pack_forget()

    # ======================== 数据持久化 ========================

    def _schedule_auto_save(self) -> None:
        """调度下一次自动保存。"""
        if self._dirty:
            self._do_auto_save()
        if self._running:
            self._auto_save_id = self._root.after(
                self._auto_save_interval, self._schedule_auto_save
            )

    def _do_auto_save(self) -> None:
        """自动保存收集的数据到文件（v2 格式：fields dict + 列信息）。"""
        try:
            with open(self._data_file, "w", encoding="utf-8") as f:
                json.dump({
                    "version": 2,
                    "count": len(self._row_data),
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "columns": self._template_headers,
                    "mapped_fields": [
                        f or "" for f in self._mapped_fields
                    ],
                    "items": self._row_data,
                }, f, ensure_ascii=False, indent=2)

            self._dirty = False
            logger.debug("自动保存完成 | %d 条记录", len(self._row_data))
        except Exception as e:
            logger.warning("自动保存失败: %s", e)

    def _restore_saved_data(self) -> None:
        """启动时恢复上次未取走的数据。兼容 v1 和 v2 格式。

        是否恢复由配置 auto_restore_data 控制（不再弹窗询问）。
        """
        if not os.path.exists(self._data_file):
            return

        # 配置开关关闭 → 静默跳过，不弹窗
        if not self.config.get("auto_restore_data", True):
            logger.info("启动恢复已关闭（配置），跳过恢复上次数据")
            return

        try:
            with open(self._data_file, "r", encoding="utf-8") as f:
                saved = json.load(f)

            items = saved.get("items", [])
            if not items:
                return

            version = saved.get("version", 1)

            if version >= 2:
                # v2 格式：items 是 [{"fields": {...}, "raw": "..."}, ...]
                # 如果有保存的模版列且当前无模版，则恢复列
                saved_columns = saved.get("columns", [])
                if saved_columns and not self._has_template:
                    self._reconfigure_columns(saved_columns)

                for item in items:
                    if isinstance(item, dict) and "fields" in item:
                        self._insert_restored_row(item, item["fields"])
                    else:
                        # 旧 v2 格式兼容
                        self._insert_restored_row(
                            {"fields": item, "raw": ""}, item,
                        )
            else:
                # v1 格式：items 是 [{"name": ..., "phone": ..., "address": ...}, ...]
                for item in items:
                    fields = empty_fields_dict()
                    fields["name"] = item.get("name", "")
                    fields["phone"] = item.get("phone", "")
                    fields["full_address"] = item.get("address", "")
                    self._insert_restored_row({"fields": fields, "raw": ""}, fields)

            self._capture_count = len(self._row_data)
            self._update_count_display()
            logger.info("数据恢复完成 | v%d | %d 条", version, self._capture_count)

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("数据恢复失败（文件损坏）: %s", e)
            try:
                corrupted = self._data_file + ".corrupted"
                os.replace(self._data_file, corrupted)
            except OSError:
                pass
        except Exception as e:
            logger.warning("数据恢复失败: %s", e)

    # ======================== 诊断 ========================

    def _dump_diagnostics(self, event=None) -> None:
        """将关键状态 dump 到日志文件（通过 Ctrl+Shift+D 触发）。"""
        try:
            preview_len = len(self._preview_text.get("1.0", tk.END).strip())
        except Exception:
            preview_len = -1

        try:
            clip_len = len(self._safe_read_clipboard())
        except Exception:
            clip_len = -1

        recent_history = self._dc_history[-5:] if self._dc_history else []

        logger.info("=" * 50)
        logger.info("诊断信息 (Ctrl+Shift+D)")
        logger.info("  running=%s | degraded=%s | dc_enabled=%s | dc_paused=%s",
                    self._running, self._degraded, self._dc_enabled, self._dc_paused)
        logger.info("  poll_count=%d | last_poll=%.1fs ago | dc_poll_id=%s",
                    self._poll_count,
                    time.time() - self._last_poll_time if self._last_poll_time else -1,
                    "active" if self._dc_poll_id else "None")
        logger.info("  clip_len=%d | preview_len=%d | last_clip_len=%d",
                    clip_len, preview_len, len(self._last_clipboard))
        logger.info("  row_count=%d | has_template=%s",
                    len(self._row_data), self._has_template)
        logger.info("  errors=%d (%d/min) | cooldown=%.1fs left",
                    self._error_count, len(self._error_timestamps),
                    max(0, self._dc_cooldown_until - time.time()))
        logger.info("  dc_interval=%.0fms | dc_pos_tolerance=%d",
                    self._dc_interval * 1000, self._dc_pos_tolerance)
        logger.info("  mouse: was_down=%s | last_click=%.1fs ago | last_pos=(%d,%d)",
                    self._mouse_was_down,
                    time.time() - self._mouse_last_click if self._mouse_last_click else -1,
                    self._mouse_last_x, self._mouse_last_y)
        logger.info("  最近连击记录 (最多 5 条):")
        for ts, x, y in recent_history:
            logger.info("    %s | (%d, %d) | %.1fs ago",
                        time.strftime("%H:%M:%S", time.localtime(ts)),
                        x, y, time.time() - ts)
        logger.info("=" * 50)
        self._flash_status("📊 诊断信息已写入日志", duration=2000)

    # ======================== 生命周期 ========================

    def _on_close(self) -> None:
        """关闭应用 — 优雅退出。"""
        logger.info("正在关闭应用...")
        self._running = False

        # 停止轮询
        self._stop_mouse_poll()
        self._clipboard_worker.stop()
        if self._auto_save_id:
            self._root.after_cancel(self._auto_save_id)
            self._auto_save_id = None

        # 最后保存
        self._do_auto_save()

        # 如果数据未被取走，提醒用户
        if self._capture_count > 0:
            try:
                should_exit = messagebox.askyesno(
                    "确认退出",
                    f"收集区还有 {self._capture_count} 条未取走的数据。\n\n"
                    f"数据已自动保存，下次启动可恢复。\n"
                    f"确定退出吗？",
                )
                if not should_exit:
                    self._running = True
                    self._schedule_auto_save()
                    return
            except Exception:
                pass

        logger.info("应用已关闭 | 总共处理 %d 条记录", self._capture_count)
        self._root.destroy()

    def run(self) -> None:
        """启动主循环。"""
        try:
            self._root.mainloop()
        except KeyboardInterrupt:
            logger.info("用户中断")
        except Exception as e:
            log_exception(logger, e, "主循环异常")
            show_error_dialog(
                "应用错误",
                "产地快打遇到了一个意外错误。\n\n"
                "崩溃日志已保存，请将此日志发送给开发者以帮助排查问题。",
                str(e),
            )

    @staticmethod
    def _single_prefill_values(profiles: list[dict]) -> dict:
        """把历史预制档案合并为单一预制信息，后者覆盖前者。"""
        merged: dict = {}
        for p in profiles or []:
            for k, v in (p.get("values") or {}).items():
                if str(v).strip():
                    merged[k] = str(v).strip()
        return merged

    @staticmethod
    def _validate_prefill(values: dict) -> list[str]:
        """校验预制信息：手机/座机二选一必填，其余字段必填。

        返回缺失提示列表，为空表示校验通过。
        """
        missing = []
        for field in PREFILL_REQUIRED_FIELDS:
            if not str(values.get(field, "")).strip():
                missing.append(f"{field} 为必填项")
        if not str(values.get("寄件人手机", "")).strip() and not str(
                values.get("寄件人座机", "")).strip():
            missing.append("寄件人手机、寄件人座机至少填写一项")
        return missing


# ======================== 启动自检 ========================


def _startup_check() -> bool:
    """
    启动环境自检，发现问题时发出警告。

    Returns:
        True 表示检查通过
    """
    issues = []

    # Python 版本
    if sys.version_info < (3, 8):
        issues.append("Python 版本过低（需要 3.8+），当前: " + sys.version)

    # 平台
    if sys.platform != "win32":
        issues.append("产地快打仅支持 Windows 系统")

    # 配置文件权限
    config_dir = app_dir()
    try:
        test_file = os.path.join(config_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
    except (OSError, PermissionError):
        issues.append(
            f"配置目录无写入权限: {config_dir}\n"
            "配置保存和日志功能将不可用"
        )

    # tkinter 可用性
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception as e:
        issues.append(f"GUI 环境不可用: {e}")

    if issues:
        issue_text = "\n\n".join(f"• {i}" for i in issues)
        show_warning_dialog(
            "启动警告",
            f"产地快打检测到以下问题:\n\n{issue_text}\n\n"
            "部分功能可能不可用。",
        )
        logger.warning("启动检查发现问题:\n%s", issue_text)
        return False

    logger.info("启动检查通过")
    return True


# ======================== 入口 ========================


def main() -> None:
    """主入口。"""
    global _single_instance_handle

    # 1. 安装崩溃处理器
    install_crash_handler()

    # 1.5 单实例互斥：已有实例运行时直接退出
    _single_instance_handle = acquire_single_instance()
    if _single_instance_handle is None:
        show_warning_dialog("已在运行", "产地快打已在运行中，请勿重复打开。")
        sys.exit(0)

    # 2. 加载配置
    config = load_config()

    # 3. 启动自检
    _startup_check()

    # 4. 创建并运行应用
    try:
        app = App(config)
        app.run()
    except Exception as e:
        log_exception(logger, e, "应用启动失败")
        show_error_dialog(
            "启动失败",
            "产地快打无法启动。\n\n"
            "请检查:\n"
            "  1. 是否有其他实例正在运行\n"
            "  2. 配置文件是否损坏（可尝试删除 config.json 恢复默认）\n"
            "  3. Python 环境是否正常",
            str(e),
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
