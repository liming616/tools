"""
悬浮弹窗 — 双击微信消息后显示解析结果

- 无边框小窗口，出现在屏幕右下角（通知区域上方）
- 3秒无操作自动消失
- 点击「发送」→ 自动切换到打单软件并填充
- 点击「忽略」→ 关闭弹窗
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
from typing import Callable, Optional

# 打单软件的窗口标题关键词（用户可自定义）
TARGET_WINDOW_KEYWORDS = []  # type: list[str]


def set_target_keywords(keywords):  # type: (list[str]) -> None
    """设置打单软件窗口关键词。"""
    global TARGET_WINDOW_KEYWORDS
    TARGET_WINDOW_KEYWORDS = keywords


class OrderOverlay:
    """订单识别结果悬浮窗。"""

    def __init__(
        self,
        summary: str,
        formatted_text: str,
        on_send: Optional[Callable] = None,
        on_dismiss: Optional[Callable] = None,
        auto_dismiss: float = 5.0,
    ):
        """
        Args:
            summary: 摘要文本（如 "张三 | 138xxxx | 2件商品"）
            formatted_text: 完整格式化文本（用于粘贴到打单软件）
            on_send: 用户点击「发送」后的回调
            on_dismiss: 用户关闭窗口后的回调
            auto_dismiss: 自动消失秒数，0 表示不自动消失
        """
        self._summary = summary
        self._formatted = formatted_text
        self._on_send = on_send
        self._on_dismiss = on_dismiss
        self._auto_dismiss = auto_dismiss

        self._root = tk.Toplevel()
        self._build()
        self._position()
        self._root.lift()
        self._root.focus_force()

        if auto_dismiss > 0:
            self._root.after(int(auto_dismiss * 1000), self._auto_close)

    def _build(self):
        self._root.title("")
        self._root.overrideredirect(True)  # 无边框
        self._root.attributes("-topmost", True)  # 置顶

        # 外观
        bg = "#2C3E50"
        fg = "#ECF0F1"
        accent = "#3498DB"

        frame = tk.Frame(
            self._root, bg=bg, bd=1, relief=tk.FLAT,
            highlightbackground="#1A252F", highlightthickness=1,
            padx=14, pady=10,
        )
        frame.pack(fill=tk.BOTH, expand=True)

        # 标题行
        title_frame = tk.Frame(frame, bg=bg)
        title_frame.pack(fill=tk.X)

        tk.Label(
            title_frame, text="📋 检测到订单",
            fg="#F39C12", bg=bg,
            font=("Microsoft YaHei", 11, "bold"),
        ).pack(side=tk.LEFT)

        # 关闭按钮
        tk.Label(
            title_frame, text="✕", fg="#95A5A6", bg=bg,
            font=("Microsoft YaHei", 10), cursor="hand2",
        ).pack(side=tk.RIGHT)
        title_frame.winfo_children()[-1].bind("<Button-1>", lambda e: self.dismiss())

        # 内容摘要
        tk.Label(
            frame, text=self._summary, fg=fg, bg=bg,
            font=("Microsoft YaHei", 9), justify=tk.LEFT,
            wraplength=300,
        ).pack(fill=tk.X, pady=(8, 12))

        # 按钮
        btn_frame = tk.Frame(frame, bg=bg)
        btn_frame.pack(fill=tk.X)

        send_btn = tk.Label(
            btn_frame, text="📤 发送到打单软件",
            fg="white", bg=accent,
            font=("Microsoft YaHei", 10, "bold"),
            padx=16, pady=8,
            cursor="hand2",
        )
        send_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        send_btn.bind("<Button-1>", lambda e: self._do_send())
        send_btn.bind("<Enter>", lambda e: send_btn.configure(bg="#2980B9"))
        send_btn.bind("<Leave>", lambda e: send_btn.configure(bg=accent))

        ignore_btn = tk.Label(
            btn_frame, text="忽略", fg="#7F8C8D", bg=bg,
            font=("Microsoft YaHei", 9), padx=10, pady=6,
            cursor="hand2",
        )
        ignore_btn.pack(side=tk.RIGHT, padx=(10, 0))
        ignore_btn.bind("<Button-1>", lambda e: self.dismiss())

    def _position(self):
        """定位到屏幕右下角。"""
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        # 先更新一下获取实际尺寸
        self._root.update_idletasks()
        w = self._root.winfo_reqwidth()
        h = self._root.winfo_reqheight()
        x = sw - w - 20
        y = sh - h - 60  # 在任务栏上方
        self._root.geometry(f"+{x}+{y}")

    def _do_send(self):
        """发送按钮回调。"""
        # 先将格式化文本写入剪贴板
        import ctypes as ct
        import ctypes.wintypes as ctw
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        u32, k32 = ct.windll.user32, ct.windll.kernel32
        # 修复 64 位 Windows 下 restype 默认 c_long (32-bit) 导致的句柄截断问题
        u32.OpenClipboard.restype = ctw.BOOL
        u32.OpenClipboard.argtypes = [ctw.HWND]
        u32.EmptyClipboard.restype = ctw.BOOL
        u32.SetClipboardData.restype = ctw.HANDLE
        u32.SetClipboardData.argtypes = [ctw.UINT, ctw.HANDLE]
        k32.GlobalAlloc.restype = ctw.HGLOBAL
        k32.GlobalAlloc.argtypes = [ctw.UINT, ct.c_size_t]
        k32.GlobalLock.restype = ct.c_void_p
        k32.GlobalLock.argtypes = [ctw.HGLOBAL]
        k32.GlobalUnlock.restype = ctw.BOOL
        k32.GlobalUnlock.argtypes = [ctw.HGLOBAL]
        u32.OpenClipboard(0)
        u32.EmptyClipboard()
        txt = self._formatted
        buf = ct.create_unicode_buffer(txt)
        h = k32.GlobalAlloc(GMEM_MOVEABLE, (len(txt) + 1) * 2)
        p = k32.GlobalLock(h)
        ct.cdll.msvcrt.wcscpy(ct.c_wchar_p(p), buf)
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        u32.CloseClipboard()

        if self._on_send:
            self._on_send(self._formatted)

        self._close()

    def _auto_close(self):
        """自动消失。"""
        if self._root.winfo_exists():
            self.dismiss()

    def dismiss(self):
        """关闭弹窗。"""
        if self._on_dismiss:
            self._on_dismiss()
        self._close()

    def _close(self):
        try:
            self._root.destroy()
        except Exception:
            pass

    @property
    def is_alive(self) -> bool:
        try:
            return self._root.winfo_exists()
        except Exception:
            return False


def show_overlay(
    summary: str,
    formatted_text: str,
    on_send: Optional[Callable] = None,
    on_dismiss: Optional[Callable] = None,
    auto_dismiss: float = 5.0,
) -> OrderOverlay:
    """
    在主线程中创建并显示悬浮窗。

    必须在主线程（tkinter 线程）中调用。
    """
    # 确保有一个隐藏的 root 来支撑 Toplevel
    try:
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
    except Exception:
        root = tk.Tk()
        root.withdraw()

    overlay = OrderOverlay(
        summary=summary,
        formatted_text=formatted_text,
        on_send=on_send,
        on_dismiss=on_dismiss,
        auto_dismiss=auto_dismiss,
    )
    return overlay
