"""
剪贴板监控模块 - 轮询检测剪贴板变化

策略（按优先级）:
  1. pyperclip — 跨平台，Windows 上稳定
  2. ctypes + Windows API — 零依赖，Windows 原生
  3. tkinter — 兜底
"""

import time
import threading
import sys
from typing import Callable, Optional

# ---------- 剪贴板读取实现 ----------

def _get_clipboard_pyperclip() -> str:
    """通过 pyperclip 读取剪贴板。"""
    import pyperclip
    text = pyperclip.paste()
    return text if isinstance(text, str) else ""


def _get_clipboard_win32() -> str:
    """通过 Windows API 直接读取剪贴板（零依赖）。"""
    import ctypes
    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    CF_UNICODETEXT = 13

    # 修复 64 位 Windows 下 restype 默认 c_long (32-bit) 导致的句柄截断问题
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    # 打开剪贴板
    if not user32.OpenClipboard(0):
        return ""

    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""

        # 获取数据指针
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""

        try:
            text = ctypes.wstring_at(ptr)
            return text if text else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _get_clipboard_tkinter() -> str:
    """通过 tkinter 读取剪贴板。"""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    try:
        text = root.clipboard_get()
        return text if isinstance(text, str) else ""
    except Exception:
        return ""
    finally:
        root.destroy()


def _select_clipboard_impl() -> Callable[[], str]:
    """选择最佳可用的剪贴板实现。"""
    # 1. pyperclip（Windows 上最可靠）
    try:
        import pyperclip
        pyperclip.paste()  # 测试调用
        return _get_clipboard_pyperclip
    except Exception:
        pass

    # 2. Windows API（零依赖）
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll  # 测试是否在 Windows 上
            _get_clipboard_win32()  # 测试调用
            return _get_clipboard_win32
        except Exception:
            pass

    # 3. tkinter 兜底
    try:
        import tkinter
        return _get_clipboard_tkinter
    except Exception:
        pass

    # 不可用
    return lambda: ""


# ---------- 监控器 ----------

class ClipboardMonitor:
    """监控剪贴板变化，当检测到新文本时调用回调。"""

    def __init__(
        self,
        callback: Callable[[str], None],
        interval: float = 0.5,
    ):
        self._callback = callback
        self._interval = interval
        self._last_text: Optional[str] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._get_clipboard = _select_clipboard_impl()

    @property
    def available(self) -> bool:
        """剪贴板读取是否可用。"""
        try:
            self._get_clipboard()
            return True
        except Exception:
            return False

    def start(self) -> None:
        """启动后台监控线程。"""
        if self._running:
            return
        self._running = True
        try:
            self._last_text = self._get_clipboard()
        except Exception:
            self._last_text = ""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止监控。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while self._running:
            try:
                current = self._get_clipboard()
            except Exception:
                time.sleep(self._interval)
                continue

            if current and current != self._last_text:
                self._last_text = current
                try:
                    self._callback(current)
                except Exception:
                    pass

            time.sleep(self._interval)

    def read_now(self) -> str:
        """立即读取当前剪贴板内容。"""
        try:
            return self._get_clipboard()
        except Exception:
            return ""
