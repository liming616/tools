"""寄件信息配置弹窗：默认寄件人 + 全局流向产品策略。"""

import tkinter as tk
from tkinter import ttk, messagebox

from config_manager import get_default_temperature, get_flow_strategies


class SenderConfigDialog(tk.Toplevel):
    """寄件信息配置弹窗。

    上半部分：默认寄件人通用信息（姓名/手机/座机/地址/物品类型/温层）。
    下半部分：流向产品配置，按当前模板分组单选。
    保存时通过 on_save 回调写回 config。
    """

    def __init__(self, master, app_config, config, template_key, on_save):
        super().__init__(master)
        self._app_config = app_config
        self._config = config
        self._template_key = template_key
        self._on_save = on_save
        self._strategy_var = tk.StringVar(value="")

        self.title("寄件信息配置")
        """寄件信息配置面板"""
        self.geometry("600x680")
        self.resizable(False, False)
        self.grab_set()

        default = self._config.get("default_sender") or {}
        self._default_vars = {
            "寄件人姓名": tk.StringVar(value=default.get("sender_name", "")),
            "寄件人手机": tk.StringVar(value=default.get("sender_phone", "")),
            "寄件人座机": tk.StringVar(value=default.get("sender_landline", "")),
            "寄件人地址": tk.StringVar(value=default.get("sender_address", "")),
            "物品类型": tk.StringVar(value=default.get("items_text", "")),
            "温层": tk.StringVar(value=(default.get("temperature_layer") or get_default_temperature(app_config))),
        }

        self._build_ui()

    def _build_ui(self) -> None:
        """构建弹窗控件。"""
        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        # ---- 默认寄件人 ----
        basics = ttk.LabelFrame(container, text=" 通用信息 ", padding=(12, 8))
        basics.pack(fill=tk.X, pady=(0, 12))
        fields = [
            ("寄件人姓名", "寄件人姓名"),
            ("寄件人手机", "寄件人手机"),
            ("寄件人座机", "寄件人座机"),
            ("寄件人地址", "寄件人地址"),
            ("物品类型", "物品类型"),
            ("温层", "温层"),
        ]
        for i, (label, key) in enumerate(fields):
            row, col = divmod(i, 2)
            ttk.Label(basics, text=label).grid(row=row, column=col * 2, sticky="w", padx=(0, 6), pady=4)
            ttk.Entry(basics, textvariable=self._default_vars[key], width=24).grid(
                row=row, column=col * 2 + 1, sticky="ew", padx=(0, 12), pady=4
            )
        basics.grid_columnconfigure(1, weight=1)
        basics.grid_columnconfigure(3, weight=1)

        # ---- 流向产品配置 ----
        flow = ttk.LabelFrame(container, text=" 流向产品配置 ", padding=(12, 8))
        flow.pack(fill=tk.BOTH, expand=True)
        strategies = get_flow_strategies(self._app_config, self._template_key)
        if not strategies:
            ttk.Label(flow, text="当前模板未配置流向策略").pack(anchor="w")
        else:
            # 优先回显已保存的选中策略；缺失或已不在策略列表时才回退第一条，
            # 避免打开弹窗后默认选中第一条导致保存时误覆盖用户之前的配置。
            saved = ((self._config.get("selected_strategy") or {}).get(self._template_key) or "")
            strategy_ids = {s.get("id") for s in strategies}
            self._strategy_var.set(saved if saved in strategy_ids else strategies[0]["id"])
            for s in strategies:
                ttk.Radiobutton(
                    flow, text=s.get("name", s.get("id", "")), value=s.get("id", ""),
                    variable=self._strategy_var,
                ).pack(anchor="w", pady=2)

        # ---- 底部按钮 ----
        footer = ttk.Frame(container)
        footer.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(footer, text="保存", command=self._on_confirm).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(footer, text="取消", command=self.destroy).pack(side=tk.RIGHT)

    def _on_confirm(self) -> None:
        """保存默认寄件人与流向策略，写回 config 并关闭弹窗。"""
        fields = self.collect_default_fields()
        default = self._config.setdefault("default_sender", {})
        default.update(fields)
        if self._strategy_var.get():
            selected = self._config.setdefault("selected_strategy", {})
            selected[self._template_key] = self._strategy_var.get()
        if self._on_save:
            self._on_save(self._config)
        self.destroy()

    def collect_default_fields(self) -> dict:
        """收集默认寄件人字段（供测试与保存）。"""
        return {
            "sender_name": self._default_vars["寄件人姓名"].get().strip(),
            "sender_phone": self._default_vars["寄件人手机"].get().strip(),
            "sender_landline": self._default_vars["寄件人座机"].get().strip(),
            "sender_address": self._default_vars["寄件人地址"].get().strip(),
            "items_text": self._default_vars["物品类型"].get().strip(),
            "temperature_layer": self._default_vars["温层"].get().strip(),
        }
