"""
产地快打 — 安全剪贴板操作模块

用 Windows API 替代 tkinter 的 clipboard_get()，解决以下问题：
  1. tkinter clipboard_get() 在剪贴板被其他进程持有时会无限阻塞主线程
  2. 无法检测 Ctrl+C 后剪贴板是否真的发生了变化

核心函数：
  - safe_read_clipboard()     → 带超时的剪贴板读取
  - safe_write_clipboard()    → 带重试的剪贴板写入
  - send_ctrl_c()             → 发送 Ctrl+C 按键
  - read_clipboard_after_ctrl_c() → Ctrl+C 后主动轮询等待剪贴板变化
"""

import ctypes
import ctypes.wintypes as w
import time
import logging
from typing import Optional

logger = logging.getLogger("moshidadan.clipboard")

# ======================== Windows API ========================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [w.HGLOBAL]
kernel32.GlobalUnlock.restype = w.BOOL
kernel32.GlobalUnlock.argtypes = [w.HGLOBAL]
kernel32.GlobalAlloc.restype = w.HGLOBAL
kernel32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [w.HGLOBAL]

# 修复 64 位 Windows 下 restype 默认 c_long (32-bit) 导致的句柄截断问题
user32.OpenClipboard.restype = w.BOOL
user32.OpenClipboard.argtypes = [w.HWND]
user32.CloseClipboard.restype = w.BOOL
user32.EmptyClipboard.restype = w.BOOL
user32.GetClipboardData.restype = w.HANDLE
user32.GetClipboardData.argtypes = [w.UINT]
user32.GetClipboardSequenceNumber.restype = w.DWORD
user32.SetClipboardData.restype = w.HANDLE
user32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


# ======================== 剪贴板读取（带超时）========================


def get_clipboard_sequence() -> int:
    """
    获取剪贴板全局序列号（不打开剪贴板，无锁竞争）。

    Windows 每次 SetClipboardData 都会递增该值，可作为低开销的变化检测信号。
    """
    return int(user32.GetClipboardSequenceNumber())


def safe_read_clipboard(timeout_ms: int = 500) -> Optional[str]:
    """
    使用 Windows API 直接读取剪贴板，带超时保护。

    与 tkinter clipboard_get() 不同，此函数不会无限阻塞。

    Args:
        timeout_ms: 最大等待时间（毫秒）

    Returns:
        成功时返回剪贴板文本（可能为空字符串），失败返回 None
    """
    interval = 50  # 每次重试间隔
    max_attempts = max(1, timeout_ms // interval)

    for attempt in range(max_attempts):
        if user32.OpenClipboard(0):
            break
        if attempt < max_attempts - 1:
            time.sleep(interval / 1000.0)
    else:
        logger.warning("safe_read_clipboard: OpenClipboard 超时 (%dms)", timeout_ms)
        return None

    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return ""

        ptr = kernel32.GlobalLock(h_data)
        if not ptr:
            return None

        try:
            size = kernel32.GlobalSize(h_data)
            if size <= 0:
                return ""
            # 安全读取，限制最大 1MB
            max_chars = min(size // 2, 1_000_000)
            raw = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_wchar))
            # 手动构建字符串，避免 c_wchar_p 的截断问题
            text = raw[:max_chars]
            # 截断到第一个 null
            null_pos = text.find('\x00')
            if null_pos >= 0:
                text = text[:null_pos]
            return text
        finally:
            kernel32.GlobalUnlock(h_data)
    except Exception as e:
        logger.debug("safe_read_clipboard: 读取异常: %s", e)
        return None
    finally:
        user32.CloseClipboard()


# ======================== 剪贴板写入（带重试）========================


def safe_write_clipboard(text: str, retries: int = 3) -> bool:
    """
    将文本写入剪贴板（带重试）。

    Returns:
        True 表示写入成功
    """
    for attempt in range(retries):
        try:
            if not user32.OpenClipboard(0):
                if attempt < retries - 1:
                    time.sleep(0.05)
                    continue
                logger.warning("safe_write_clipboard: OpenClipboard 失败")
                return False

            user32.EmptyClipboard()
            buf = ctypes.create_unicode_buffer(text)
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, (len(text) + 1) * 2)
            if not handle:
                user32.CloseClipboard()
                if attempt < retries - 1:
                    time.sleep(0.1)
                continue

            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                kernel32.GlobalFree(handle)
                user32.CloseClipboard()
                if attempt < retries - 1:
                    time.sleep(0.1)
                continue

            ctypes.cdll.msvcrt.wcscpy(ctypes.c_wchar_p(ptr), buf)
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(CF_UNICODETEXT, handle)
            user32.CloseClipboard()
            return True
        except Exception as e:
            logger.warning("safe_write_clipboard 失败 (attempt %d/%d): %s",
                           attempt + 1, retries, e)
            try:
                user32.CloseClipboard()
            except Exception:
                pass
            if attempt < retries - 1:
                time.sleep(0.1)
    return False


# ======================== Ctrl+C 发送 ========================


def send_ctrl_c() -> bool:
    """
    发送 Ctrl+C 按键。

    策略：
      1. 优先使用 SendInput（精确模拟键盘输入）
      2. SendInput 可能因 UIPI 或结构体对齐问题返回 0
         → 回退到 keybd_event（兼容性更好，但已标记为 deprecated）
      3. 两者都失败时记录 Windows 错误码

    Returns:
        True 表示按鍵已发送（不代表目标应用确实复制了文本）
    """
    VK_CONTROL = 0x11
    VK_C = 0x43
    KEYEVENTF_KEYUP = 0x0002

    # ---- 方法 1: SendInput（精确模拟）----
    try:
        INPUT_KEYBOARD = 1

        # 必须包含 MOUSEINPUT 和 HARDWAREINPUT 确保 union 大小与 Windows ABI 一致
        # 缺少任一成员会导致 sizeof(INPUT) 偏小，SendInput 拒绝调用
        class MOUSEINPUT(ctypes.Structure):
            _pack_ = 8
            _fields_ = [
                ("dx", w.LONG),
                ("dy", w.LONG),
                ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD),
                ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_ulonglong),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _pack_ = 8
            _fields_ = [
                ("wVk", w.WORD),
                ("wScan", w.WORD),
                ("dwFlags", w.DWORD),
                ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_ulonglong),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _pack_ = 8
            _fields_ = [
                ("uMsg", w.DWORD),
                ("wParamL", w.WORD),
                ("wParamH", w.WORD),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _pack_ = 8
            _fields_ = [("type", w.DWORD), ("union", INPUT_UNION)]

        cb_size = ctypes.sizeof(INPUT)
        logger.debug("send_ctrl_c: sizeof(INPUT)=%d (64-bit expect 40)", cb_size)

        def _make_input(vk, up=False):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.union.ki.wVk = vk
            inp.union.ki.wScan = 0
            inp.union.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
            inp.union.ki.time = 0
            inp.union.ki.dwExtraInfo = 0
            return inp

        inputs = [
            _make_input(VK_CONTROL),
            _make_input(VK_C),
            _make_input(VK_C, up=True),
            _make_input(VK_CONTROL, up=True),
        ]
        arr = (INPUT * len(inputs))(*inputs)
        sent = ctypes.windll.user32.SendInput(len(inputs), arr, cb_size)

        if sent == len(inputs):
            logger.debug("send_ctrl_c: SendInput 成功 | events=%d", sent)
            return True

        # SendInput 失败 — 记录错误码并回退
        err = ctypes.get_last_error()
        logger.debug("send_ctrl_c: SendInput 返回 %d (期望 %d) | WinErr=%d",
                     sent, len(inputs), err)
    except Exception as e:
        logger.debug("send_ctrl_c: SendInput 异常: %s，回退到 keybd_event", e)

    # ---- 方法 2: keybd_event（兼容性回退）----
    try:
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_C, 0, 0, 0)
        user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        logger.debug("send_ctrl_c: keybd_event 回退成功")
        return True
    except Exception as e:
        logger.warning("send_ctrl_c: keybd_event 也失败: %s", e)
        return False


# ======================== Ctrl+C 后主动读取 ========================


def read_clipboard_after_ctrl_c(
    prev_text: str,
    timeout_ms: int = 800,
    poll_interval_ms: int = 80,
) -> Optional[str]:
    """
    在 send_ctrl_c() 之后主动轮询剪贴板，等待内容变化。

    解决原来依赖独立剪贴板轮询（400ms 间隔）的时序问题：
    Ctrl+C 发送后，剪贴板可能在几毫秒到几百毫秒内更新。
    此函数主动等待变化，一旦检测到就立即返回。

    Args:
        prev_text: send_ctrl_c 之前的剪贴板内容
        timeout_ms: 最大等待时间
        poll_interval_ms: 轮询间隔

    Returns:
        新剪贴板内容（若变化），None（若超时未变化）
    """
    deadline = time.time() + timeout_ms / 1000.0

    while time.time() < deadline:
        time.sleep(poll_interval_ms / 1000.0)
        new_text = safe_read_clipboard(timeout_ms=100)

        if new_text and new_text.strip() and new_text.strip() != prev_text.strip():
            logger.debug("read_clipboard_after_ctrl_c: 检测到变化 | prev_len=%d → new_len=%d",
                         len(prev_text), len(new_text))
            return new_text

    logger.debug("read_clipboard_after_ctrl_c: 超时 %dms，剪贴板未变化 | prev_len=%d",
                 timeout_ms, len(prev_text))
    return None


# ======================== 前台窗口工具 ========================


def get_foreground_title() -> str:
    """获取前台窗口标题（带异常保护）。"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


def is_wechat_active(keywords) -> bool:
    """判断前台窗口标题是否匹配微信关键词。"""
    try:
        title = get_foreground_title()
        if not title:
            return False
        return any(kw.lower() in title.lower() for kw in keywords)
    except Exception:
        return False
