"""产地快打主窗口布局：顶栏/寄件人选项卡/寄收区/列表/一键保存/版本号。"""

import os
import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

from template_manager import get_list_headers

# 配色（白底 + 京东蓝主按钮 + 灰描述边，贴近原型图）
COLOR_BG = "#FFFFFF"
COLOR_BLUE = "#5793DF"
COLOR_BLUE_DIM = "#4A87D6"
COLOR_HEADER = "#E8E8E8"
COLOR_BORDER = "#D9D9D9"
COLOR_TEXT = "#333333"
COLOR_TEXT_DIM = "#8A8A8A"
COLOR_SELECT_BG = "#BFD7F7"

FONT_BODY = ("Microsoft YaHei", 10)
FONT_BODY_B = ("Microsoft YaHei", 10, "bold")
FONT_MONO = ("Consolas", 10)

# 寄件人卡片输入框 -> sender_profiles 档案字段键
SENDER_FIELD_MAP = {
    "寄件人姓名": "sender_name",
    "寄件人手机": "sender_phone",
    "寄件人座机": "sender_landline",
    "寄件人地址": "sender_address",
    "物品类型": "items_text",
    "温层": "temperature_layer",
}

# 地址类/备注类列固定加宽（默认 120 的两倍），其余列保持默认宽度；
# 横向滚动条由 _build_table 提供，超宽可由滚动查看到全部表头
WIDE_COLUMN_WIDTHS = {
    "寄件人地址": 360,
    "收件人地址": 360,
    "详细地址(省+市+区/县+街道号+门牌号)": 480,
    "面单备注": 360,
    "运单备注": 360,
}

# 列表多选：选择列名与勾选状态字形
SELECT_COL = "选择"
CHECK_ON = "☑"
CHECK_OFF = "☐"


class AppFrame(tk.Tk):
    """产地快打主窗口。

    只负责 UI 布局与事件转发；业务逻辑（识别、匹配、导出、持久化）
    由 main.App 通过回调注入。
    """

    def __init__(self, config, app_config):
        super().__init__()
        self._config = config or {}
        self._app_config = app_config or {}
        self._template_key = self._config.get("selected_template", "JD_MONTHLY")
        self._template_meta = self._parse_template_options(self._app_config)
        self._list_headers = list(self._resolve_list_headers())
        self._sender_sel = tk.StringVar(value=self._config.get("selected_sender", "寄件人1"))
        self._auto_var = tk.BooleanVar(value=bool(self._config.get("auto_recognize", False)))
        self._combo_var = tk.BooleanVar(value=bool(self._config.get("combo_copy", True)))
        self._version = str(app_config.get("version", "")).strip()
        self._focus_target = ""

        # 外部回调（由 main.App 注入）
        self.on_template_changed = None
        self.on_auto_toggle = None
        self.on_combo_toggle = None
        self.on_recognize = None
        self.on_save = None
        self.on_config_clicked = None
        self.on_save_dir_clicked = None
        self.on_help_clicked = None
        self.on_row_checked = None
        self.on_select_all = None
        self.on_delete_selected = None

        self._build_style()
        self._build_ui()
        self._apply_template(self._template_key)
        self._show_version()

    # ---------- 样式 ----------
    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, font=FONT_BODY)
        style.configure("Card.TFrame", background=COLOR_BG)
        style.configure("TCombobox", fieldbackground=COLOR_BG, background=COLOR_BG,
                        bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER,
                        darkcolor=COLOR_BORDER, arrowcolor=COLOR_TEXT, padding=6)
        self.option_add("*TCombobox*Listbox.font", FONT_BODY)

        style.configure("Outline.TButton", font=FONT_BODY, background=COLOR_BG,
                        foreground=COLOR_BLUE, bordercolor=COLOR_BLUE,
                        lightcolor=COLOR_BLUE, darkcolor=COLOR_BLUE, padding=(12, 7))
        style.map("Outline.TButton", background=[("active", "#EEF4FC")],
                  foreground=[("active", COLOR_BLUE)])

        style.configure("Green.TButton", font=FONT_BODY, background="#FFFFFF",
                        foreground=COLOR_BLUE, bordercolor=COLOR_BLUE,
                        lightcolor=COLOR_BLUE, darkcolor=COLOR_BLUE, padding=(12, 7))
        style.map("Green.TButton", background=[("active", "#EEF4FC")],
                  foreground=[("active", COLOR_BLUE)])

        style.configure("GreenActive.TButton", font=FONT_BODY, background=COLOR_BLUE,
                        foreground="#FFFFFF", bordercolor=COLOR_BLUE,
                        lightcolor=COLOR_BLUE, darkcolor=COLOR_BLUE, padding=(12, 7))
        style.map("GreenActive.TButton", background=[("active", COLOR_BLUE_DIM)],
                  foreground=[("active", "#FFFFFF")])

        style.configure("Blue.TButton", font=("Microsoft YaHei", 11, "bold"),
                        background=COLOR_BLUE, foreground="#FFFFFF",
                        bordercolor=COLOR_BLUE, padding=(18, 9))
        style.map("Blue.TButton", background=[("active", COLOR_BLUE_DIM)])

        style.configure("Recognize.TButton", font=("Microsoft YaHei", 10, "bold"),
                        background=COLOR_BLUE, foreground="#FFFFFF",
                        bordercolor=COLOR_BLUE, padding=(15, 7))
        style.map("Recognize.TButton", background=[("active", COLOR_BLUE_DIM)])

        style.configure("Tab.TButton", font=FONT_BODY, background=COLOR_BG,
                        foreground=COLOR_TEXT, bordercolor=COLOR_BORDER,
                        lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER, padding=(18, 9))
        style.map("Tab.TButton", background=[("active", "#F3F3F3")])
        style.configure("TabActive.TButton", font=FONT_BODY_B, background="#B3ED67",
                        foreground=COLOR_TEXT, bordercolor="#B3ED67", padding=(18, 9))
        style.map("TabActive.TButton", background=[("active", "#A5DE54")])

        style.configure("Treeview", font=FONT_MONO, rowheight=30, background=COLOR_BG,
                        fieldbackground=COLOR_BG, foreground=COLOR_TEXT,
                        bordercolor=COLOR_BORDER)
        style.configure("Treeview.Heading", font=FONT_BODY_B, background=COLOR_HEADER,
                        foreground=COLOR_TEXT, bordercolor=COLOR_BORDER, padding=(8, 7))
        style.map("Treeview", background=[("selected", COLOR_SELECT_BG)],
                  foreground=[("selected", COLOR_TEXT)])

    # ---------- 布局 ----------
    def _build_ui(self) -> None:
        self.geometry("1880x1000")
        self.minsize(1180, 720)
        self.configure(bg=COLOR_BG)
        pad = 18

        # 顶栏
        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill=tk.X, padx=pad, pady=(pad, 4))

        self._template_var = tk.StringVar(value=self._template_label(self._template_key))
        combo = ttk.Combobox(header, textvariable=self._template_var, state="readonly",
                             values=tuple(self._template_meta["labels"]),
                             width=18, font=FONT_BODY)
        combo.pack(side=tk.LEFT)
        combo.configure(postcommand=self._on_template_popdown)
        combo.bind("<<ComboboxSelected>>", self._on_template_selected)
        self._template_combo = combo

        right = ttk.Frame(header, style="Card.TFrame")
        right.pack(side=tk.RIGHT)
        self._build_help_button(right)
        ttk.Button(right, text="寄件信息配置", style="Outline.TButton",
                   command=lambda: self._fire(self.on_config_clicked)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(right, text="文件保存位置", style="Outline.TButton",
                   command=lambda: self._fire(self.on_save_dir_clicked)).pack(side=tk.LEFT, padx=(0, 8))
        self._auto_btn = ttk.Button(right, text="自动识别", style="Green.TButton",
                                    command=self._on_auto_toggle)
        self._auto_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._combo_btn = ttk.Button(right, text="连击复制", style="Green.TButton",
                                     command=self._on_combo_toggle)
        self._combo_btn.pack(side=tk.LEFT)
        self._refresh_toggle_style(self._auto_btn, self._auto_var.get())
        self._refresh_toggle_style(self._combo_btn, self._combo_var.get())

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=pad, pady=(4, 10))

        # 中部：寄件人选项卡 + 寄/收卡片
        middle = ttk.Frame(self, style="Card.TFrame")
        middle.pack(fill=tk.X, padx=pad, pady=(0, 14))

        sender_col = ttk.Frame(middle, style="Card.TFrame")
        sender_col.pack(side=tk.LEFT, fill=tk.Y)
        self._sender_buttons = {}
        for label in ("寄件人1", "寄件人2", "寄件人3"):
            is_active = label == self._sender_sel.get()
            style = "TabActive.TButton" if is_active else "Tab.TButton"
            btn = ttk.Button(sender_col, text=label, style=style,
                             command=lambda l=label: self._on_sender_selected(l))
            btn.pack(fill=tk.X, pady=(0, 2))
            self._sender_buttons[label] = btn

        paned = ttk.Frame(middle, style="Card.TFrame")
        paned.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 0))
        self._build_sender_card(paned)
        self._build_receiver_card(paned)
        # 初始化回填当前选中寄件人档案
        self._load_sender_texts(self._sender_sel.get())

        # 工具行：删除数据（左侧，与模板下拉/寄件人标签对齐）与文本识别（右侧）同一水平
        action_row = ttk.Frame(self, style="Card.TFrame")
        action_row.pack(fill=tk.X, padx=pad, pady=(0, 8))
        ttk.Button(action_row, text="删除数据", style="Outline.TButton",
                   command=lambda: self._fire(self.on_delete_selected)).pack(side=tk.LEFT)
        ttk.Button(action_row, text="文本识别", style="Recognize.TButton",
                   command=lambda: self._fire(self.on_recognize)).pack(side=tk.RIGHT)

        # 列表区
        table_wrap = ttk.Frame(self, style="Card.TFrame")
        table_wrap.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, 14))
        self._build_table(table_wrap)

        # 底部
        bottom = ttk.Frame(self, style="Card.TFrame")
        bottom.pack(fill=tk.X, padx=pad, pady=(0, pad))
        ttk.Button(bottom, text="一键保存", style="Blue.TButton",
                   command=lambda: self._fire(self.on_save)).pack(side=tk.RIGHT)
        if self._version:
            ttk.Label(bottom, text=self._version, foreground=COLOR_TEXT_DIM,
                      font=("Microsoft YaHei", 9)).pack(side=tk.RIGHT, padx=(0, 10))
        self._status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self._status_var, foreground=COLOR_TEXT_DIM,
                  font=FONT_BODY).pack(side=tk.LEFT)

    def _build_sender_card(self, parent: ttk.Frame) -> None:
        """寄件人信息卡片：与选中寄件人联动，使用单行文本框。"""
        card = tk.Frame(parent, bg=COLOR_BG, bd=1, relief=tk.SOLID,
                        highlightbackground=COLOR_BORDER, highlightcolor=COLOR_BORDER,
                        highlightthickness=1)
        card.pack(fill=tk.X, pady=(0, 10))
        body = tk.Frame(card, bg=COLOR_BG)
        body.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=14, pady=10)
        tk.Label(card, text="寄", font=("Microsoft YaHei", 26, "bold"),
                 bg=COLOR_BG, fg=COLOR_TEXT, padx=28, pady=20).pack(side=tk.RIGHT)

        # 与收件人区域一致的大文本框，内容始终为单行
        self._sender_text = tk.Text(body, height=6, wrap=tk.NONE, font=FONT_BODY,
                                    bg="#FFFFFF", fg=COLOR_TEXT, relief=tk.FLAT,
                                    borderwidth=1, highlightbackground=COLOR_BORDER,
                                    highlightthickness=1, padx=6, pady=4)
        self._sender_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 禁止回车换行与多行粘贴，保证仅显示一行数据
        self._sender_text.bind("<Return>", self._on_sender_key_return)
        self._sender_text.bind("<<Paste>>", self._on_sender_paste)
        # 记录用户最后进入的文本框，供剪贴板内容焦点路由
        self._sender_text.bind("<FocusIn>", self._on_sender_focus)
        self._sender_text.bind("<Button-1>", lambda e: self._mark_focus_target("sender"))

    def _build_receiver_card(self, parent: ttk.Frame) -> None:
        """收件人文本区卡片。"""
        card = tk.Frame(parent, bg=COLOR_BG, bd=1, relief=tk.SOLID,
                        highlightbackground=COLOR_BORDER, highlightcolor=COLOR_BORDER,
                        highlightthickness=1)
        card.pack(fill=tk.X)
        body = tk.Frame(card, bg=COLOR_BG)
        body.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=14, pady=10)
        tk.Label(card, text="收", font=("Microsoft YaHei", 26, "bold"),
                 bg=COLOR_BG, fg=COLOR_TEXT, padx=28, pady=20).pack(side=tk.RIGHT)
        self._receiver_text = tk.Text(body, font=FONT_BODY, height=6, wrap=tk.WORD,
                                       bg="#FFFFFF", fg=COLOR_TEXT, relief=tk.FLAT,
                                       borderwidth=1, highlightbackground=COLOR_BORDER,
                                       highlightthickness=1, padx=6, pady=4)
        self._receiver_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 记录用户最后进入的文本框，供剪贴板内容焦点路由
        self._receiver_text.bind("<FocusIn>", lambda e: self._mark_focus_target("receiver"))
        self._receiver_text.bind("<Button-1>", lambda e: self._mark_focus_target("receiver"))

    def _build_table(self, parent: ttk.Frame) -> None:
        """构建列表展示区（表头随模板切换）。"""
        container = ttk.Frame(parent, style="Card.TFrame")
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(container, show="headings", height=9)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        # 单元格可编辑
        self._tree.bind("<Double-1>", self._on_cell_edit)
        # 选择列：单击勾选、点击表头全选
        self._tree.bind("<Button-1>", self._on_tree_click)

    # ---------- 事件 ----------
    @staticmethod
    def _fire(cb) -> None:
        if callable(cb):
            cb()

    def _on_template_selected(self, event=None) -> None:
        label = self._template_var.get()
        # 禁用模板不可选中：恢复为当前模板并忽略本次选择
        if label in self._template_meta["disabled_labels"]:
            self._template_var.set(self._template_label(self._template_key))
            return
        key = self._template_meta["label_to_key"].get(label)
        if not key:
            return
        self._config["selected_template"] = key
        self._template_key = key
        self._apply_template(key)
        if callable(self.on_template_changed):
            self.on_template_changed(key)

    def _on_auto_toggle(self) -> None:
        self._auto_var.set(not self._auto_var.get())
        self._refresh_toggle_style(self._auto_btn, self._auto_var.get())
        self._config["auto_recognize"] = self._auto_var.get()
        if callable(self.on_auto_toggle):
            self.on_auto_toggle(self._auto_var.get())

    def _on_combo_toggle(self) -> None:
        self._combo_var.set(not self._combo_var.get())
        self._refresh_toggle_style(self._combo_btn, self._combo_var.get())
        self._config["combo_copy"] = self._combo_var.get()
        if callable(self.on_combo_toggle):
            self.on_combo_toggle(self._combo_var.get())

    def _on_sender_selected(self, label: str) -> None:
        """手动切换寄件人组：先保存旧组，再激活并加载新组。"""
        self._save_current_sender_texts()
        self._activate_sender_group(label)

    def _on_cell_edit(self, event) -> None:
        """双击单元格进入编辑（用 Entry 覆盖）。"""
        region = self._tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self._tree.identify_row(event.y)
        col = self._tree.identify_column(event.x)
        if not item or not col:
            return
        # 选择列不可编辑
        header = self._tree.heading(str(col or ""), "text")
        if header in (CHECK_ON, CHECK_OFF):
            return
        x, y, w, h = self._tree.bbox(item, col)
        value = self._tree.set(item, col)
        entry = tk.Entry(self._tree, font=FONT_MONO)
        entry.insert(0, value)
        entry.place(x=x, y=y, width=w, height=h)

        def commit(event=None):
            new = entry.get()
            self._tree.set(item, col, new)
            self._update_row_field(item, col, new)
            entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.focus_set()

    # ---------- 供 App 调用 ----------
    def get_tree_columns(self):
        """当前模板列表表头。"""
        return tuple(self._list_headers)

    def build_row(self, fields, serial=None, selected=False):
        """按当前模板列表表头构建显示行。"""
        values = [CHECK_ON if selected else CHECK_OFF]
        for i, header in enumerate(self._list_headers):
            if header == "序号":
                values.append(str(serial if serial is not None else i + 1))
            else:
                values.append(str(self._display_value(fields, header)))
        return tuple(values)

    def insert_row(self, values) -> str:
        """插入一行，返回 item id。"""
        return self._tree.insert("", tk.END, values=values)

    def clear_rows(self) -> None:
        """清空列表。"""
        for item in self._tree.get_children():
            self._tree.delete(item)

    def get_receiver_text(self) -> str:
        """读取收件人文本框内容。"""
        return self._receiver_text.get("1.0", tk.END).strip()

    def append_receiver(self, text: str) -> None:
        """追加文本到收件人文本框（自动识别关闭时使用）。"""
        current = self.get_receiver_text()
        new = f"{current}\n{text}" if current else text
        self._receiver_text.delete("1.0", tk.END)
        self._receiver_text.insert("1.0", new)

    def set_status(self, msg: str) -> None:
        """设置底部状态文字。"""
        self._status_var.set(msg)

    def get_template_key(self) -> str:
        """返回当前模板 key。"""
        return self._template_key

    def flush_sender_profile(self) -> None:
        """关闭前把当前寄件人/收件人文本框内容落盘到 sender_profiles。"""
        self._save_current_sender_texts()

    # ---------- 寄件人档案 ----------
    def _find_sender_profile(self, label: str) -> dict:
        """按 label 查找寄件人档案，未找到返回空 dict。"""
        for p in (self._config.get("sender_profiles") or []):
            if (p.get("label") or "") == label:
                return p
        return {}

    # ---------- 逻辑辅助 ----------
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
            "重量（kg）": "weight",
            "重量(kg)": "weight",
            "面单备注": "notes",
            "运单备注": "notes",
            "寄件人姓名": "sender_name",
            "寄件人手机": "sender_phone",
            "寄件人座机": "sender_landline",
            "寄件人地址": "sender_address",
        }
        return mapping.get(header, "")

    def _resolve_list_headers(self):
        return get_list_headers(self._template_key, self._app_config)

    def _apply_template(self, key: str) -> None:
        """切换模板：重设列表表头并清空列表。"""
        self._template_key = key
        self._list_headers = list(self._resolve_list_headers())
        self._tree.delete(*self._tree.get_children())
        all_cols = [SELECT_COL] + self._list_headers
        self._tree["columns"] = all_cols
        for col in self._list_headers:
            self._tree.heading(col, text=col)
            self._tree.column(
                col, width=WIDE_COLUMN_WIDTHS.get(col, 120),
                anchor=tk.W, stretch=False,
            )
        self._tree.heading(SELECT_COL, text=CHECK_OFF)
        self._tree.column(SELECT_COL, width=44, anchor=tk.CENTER, stretch=False)
        if "序号" in self._list_headers:
            self._tree.column("序号", width=60, anchor=tk.CENTER, stretch=False)

    def _update_row_field(self, item, col, value) -> None:
        """单元格编辑后同步到 App 数据。"""
        if callable(self.on_cell_edited):
            self.on_cell_edited(item, col, value)

    def _show_version(self) -> None:
        """标题栏显示版本号（右下角已在底部栏展示）。"""
        title = f"产地快打 {self._version}".strip()
        self.title(title)

    def _refresh_toggle_style(self, btn, active: bool) -> None:
        if btn is None:
            return
        btn.configure(style="GreenActive.TButton" if active else "Green.TButton")

    def _template_label(self, key: str) -> str:
        opts = (self._app_config.get("templates") or {}).get("options") or []
        for o in opts:
            if o.get("key") == key:
                return o.get("label", key)
        return "京东月结模板"

    def clear_receiver_text(self) -> None:
        """清空收件人文本框，避免同一批文本被再次识别。"""
        self._receiver_text.delete("1.0", tk.END)

    def _display_value(self, fields, header) -> str:
        """按列取显示值；联系方式列合并手机/座机，避免座机号丢失。"""
        if header == "联系方式":
            return str(fields.get("phone") or fields.get("landline") or "")
        key = self._field_key(header)
        return str(fields.get(key, "") if key else "")

    def _build_help_button(self, parent: ttk.Frame) -> None:
        """绘制圆形帮助按钮（Canvas 圆环 + ?），悬停与点击反馈。"""
        size = 36
        self._help_canvas = tk.Canvas(
            parent, width=size, height=size, bg=COLOR_BG,
            highlightthickness=0, bd=0, cursor="hand2",
        )
        pad = 2
        self._help_circle = self._help_canvas.create_oval(
            pad, pad, size - pad, size - pad,
            outline=COLOR_BLUE, fill=COLOR_BG, width=1.6,
        )
        self._help_text = self._help_canvas.create_text(
            size / 2, size / 2, text="?", anchor="center",
            font=("Microsoft YaHei", 10, "bold"), fill=COLOR_BLUE,
        )
        # 依据字形 bbox 动态居中：让问号视觉中心精确对齐圆心，避免字体基线偏差。
        text_bbox = self._help_canvas.bbox(self._help_text)
        if text_bbox:
            cx = cy = size / 2
            dx = cx - (text_bbox[0] + text_bbox[2]) / 2
            dy = cy - (text_bbox[1] + text_bbox[3]) / 2
            self._help_canvas.move(self._help_text, dx, dy)
        self._help_canvas.bind(
            "<Button-1>", lambda e: self._fire(self.on_help_clicked)
        )
        self._help_canvas.bind(
            "<Enter>",
            lambda e: self._help_canvas.itemconfigure(self._help_circle, fill=COLOR_SELECT_BG),
        )
        self._help_canvas.bind(
            "<Leave>",
            lambda e: self._help_canvas.itemconfigure(self._help_circle, fill=COLOR_BG),
        )
        self._help_canvas.pack(side=tk.LEFT, padx=(0, 6))

    # 面板切换时切换开关样式

    def _on_template_popdown(self) -> None:
        """下拉弹出时调度置灰，等待 Tk 完成列表填充后再着色。"""
        self.after_idle(self._tint_disabled_templates)

    def _tint_disabled_templates(self) -> None:
        """给下拉列表中的禁用模板设置灰色前景色。"""
        combo = getattr(self, "_template_combo", None)
        if combo is None:
            return
        values = list(combo.cget("values") or ())
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            listbox = popdown + ".f.l"
            size = combo.tk.call(listbox, "size")
        except tk.TclError:
            return
        for i in range(size):
            label = values[i] if i < len(values) else ""
            foreground = "#AAAAAA" if label in self._template_meta["disabled_labels"] else "#000000"
            combo.tk.call(listbox, "itemconfigure", i, "-foreground", foreground)

    @staticmethod
    def _parse_template_options(app_config) -> dict:
        """从 app_config 的 templates.options 解析下拉元数据。

        返回 dict，包含：
          - labels: 全部模板 label（含禁用项，供下拉展示）
          - label_to_key: label -> key 映射
          - disabled_labels: 被禁用模板的 label 集合
        """
        options = (app_config or {}).get("templates", {}).get("options") or []
        labels: list[str] = []
        label_to_key: dict[str, str] = {}
        disabled_labels: set[str] = set()
        for option in options:
            if not isinstance(option, dict):
                continue
            key = option.get("key")
            label = option.get("label", key)
            if not key or not label:
                continue
            labels.append(label)
            label_to_key[label] = key
            if not option.get("enabled", True):
                disabled_labels.add(label)
        return {
            "labels": labels,
            "label_to_key": label_to_key,
            "disabled_labels": disabled_labels,
        }

    # ---------- 寄件人/收件人文本框 ----------
    def get_sender_text(self) -> str:
        """读取寄件人文本框内容。"""
        return self._sender_text.get("1.0", tk.END).strip()

    def set_sender_text(self, text: str) -> None:
        """覆盖写寄件人文本框（内容折叠为单行）。"""
        self._sender_text.delete("1.0", tk.END)
        self._sender_text.insert("1.0", self._single_line(text))

    def set_receiver_text(self, text: str) -> None:
        """回填收件人文本框内容（用于切换寄件人标签回显）。"""
        self._receiver_text.delete("1.0", tk.END)
        self._receiver_text.insert("1.0", str(text or ""))

    def get_focus_target(self) -> str:
        """返回用户最后进入的目标框：'sender' / 'receiver' / ''。"""
        return getattr(self, "_focus_target", "")

    def _mark_focus_target(self, target: str) -> None:
        """记录当前进入的文本框，用于剪贴板内容路由。"""
        self._focus_target = target

    @staticmethod
    def _single_line(text: str) -> str:
        """把多行/连续空白折叠为单个空格。"""
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _on_sender_key_return(event=None):
        """寄件人文本框禁止回车换行（仅显示一行数据）。"""
        return "break"

    def _on_sender_paste(self, event=None):
        """粘贴时折叠为单行并覆盖写入，避免多行内容破坏单行约束。"""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        self.set_sender_text(text)
        return "break"

    def _load_sender_texts(self, label: str) -> None:
        """把指定寄件人档案的文本回填到寄件人/收件人文本框。"""
        profile = self._find_sender_profile(label)
        self.set_sender_text(str(profile.get("sender_text") or ""))
        self.set_receiver_text(str(profile.get("receiver_text") or ""))

    def _save_current_sender_texts(self) -> None:
        """把当前寄件人/收件人文本框内容写回 sender_profiles 对应档案。"""
        label = (self._sender_sel.get() or "").strip() or "寄件人1"
        profiles = self._config.setdefault("sender_profiles", [])
        profile = self._find_sender_profile(label)
        if not profile:
            profile = {"label": label}
            profiles.append(profile)
        profile["sender_text"] = self.get_sender_text()
        profile["receiver_text"] = self.get_receiver_text()

    # ---------- 列表多选 ----------
    def set_row_checked(self, item, checked: bool) -> None:
        """设置单行勾选状态并刷新表头全选。"""
        self._tree.set(item, SELECT_COL, CHECK_ON if checked else CHECK_OFF)
        self.update_select_header()

    def update_select_header(self) -> None:
        """根据当前行的勾选状态刷新表头全选框（全部勾选显示 ☑）。"""
        items = self._tree.get_children()
        checked = sum(1 for it in items if self._tree.set(it, SELECT_COL) == CHECK_ON)
        all_checked = bool(items) and checked == len(items)
        self._tree.heading(SELECT_COL, text=CHECK_ON if all_checked else CHECK_OFF)

    def _toggle_row(self, item) -> None:
        """切换单行勾选并通知 App 同步选中状态。"""
        checked = self._tree.set(item, SELECT_COL) != CHECK_ON
        self.set_row_checked(item, checked)
        if callable(self.on_row_checked):
            self.on_row_checked(item, checked)

    def _toggle_select_all(self) -> None:
        """切换全选/全不选，并通知 App 同步选中状态。"""
        items = self._tree.get_children()
        all_checked = bool(items) and all(
            self._tree.set(it, SELECT_COL) == CHECK_ON for it in items
        )
        new_checked = not all_checked
        for it in items:
            self._tree.set(it, SELECT_COL, CHECK_ON if new_checked else CHECK_OFF)
        self.update_select_header()
        if callable(self.on_select_all):
            self.on_select_all(new_checked)

    def _on_tree_click(self, event):
        """处理选择列单击与表头全选点击。"""
        region = self._tree.identify("region", event.x, event.y)
        col = self._tree.identify_column(event.x)
        header = self._tree.heading(str(col or ""), "text")
        if region == "heading" and header in (CHECK_ON, CHECK_OFF):
            self._toggle_select_all()
            return "break"
        if region == "cell" and header in (CHECK_ON, CHECK_OFF):
            item = self._tree.identify_row(event.y)
            if item:
                self._toggle_row(item)
            return "break"
        return None

    def _on_sender_focus(self, event=None):
        """焦点进入寄件文本框时，确保存在有效的寄件人组。"""
        self._mark_focus_target("sender")
        current = str(self._sender_sel.get() or "").strip()
        if current not in self._sender_buttons:
            self._activate_sender_group("寄件人1")

    def _activate_sender_group(self, label: str) -> None:
        """激活寄件人组并同步配置、按钮样式和文本框内容。"""
        self._sender_sel.set(label)
        self._config["selected_sender"] = label
        for group_label, button in self._sender_buttons.items():
            style = "TabActive.TButton" if group_label == label else "Tab.TButton"
            button.configure(style=style)
        self._load_sender_texts(label)
