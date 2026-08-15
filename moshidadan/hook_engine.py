"""
Windows 全局钩子引擎 — 纯 ctypes，零外部依赖

功能:
  1. 全局鼠标钩子 (WH_MOUSE_LL) — 检测双击
  2. 窗口检测 — 判断当前窗口是否为微信
  3. 键盘模拟 — 发送 Ctrl+C / Ctrl+V / Tab 等
  4. 窗口切换 — 查找并激活目标窗口
"""

import ctypes
import ctypes.wintypes as w
import queue
import threading
import time
import sys
import traceback
from typing import Callable, Optional

# ======================== Windows API 常量 ========================

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP   = 0x0202
VK_CONTROL = 0x11
VK_C = 0x43
VK_V = 0x56
VK_TAB = 0x09
VK_RETURN = 0x0D
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
PM_NOREMOVE = 0

HC_ACTION = 0
WM_QUIT = 0x0012

# 64 位安全：LRESULT / WPARAM / LPARAM 均为指针宽度
LRESULT_T = ctypes.c_ssize_t

# ======================== 结构体 ========================

class POINT(ctypes.Structure):
    _fields_ = [("x", w.LONG), ("y", w.LONG)]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", w.DWORD),
        ("flags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.POINTER(w.ULONG)),
    ]

# 函数指针类型（64 位安全：LRESULT 用指针宽度，参数用 c_void_p 避免句柄/指针截断）
HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT_T,          # LRESULT
    ctypes.c_int,       # int nCode
    ctypes.c_void_p,    # WPARAM wParam
    ctypes.c_void_p,    # LPARAM lParam
)

# SendInput 结构体（替代过时的 keybd_event）
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD),
        ("wScan", w.WORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.POINTER(w.ULONG)),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", w.DWORD),
        ("union", INPUT_UNION),
    ]

# ======================== API 绑定 ========================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 修复 64 位 Windows 下 restype 默认 c_long (32-bit) 导致的句柄截断问题
user32.OpenClipboard.restype = w.BOOL
user32.OpenClipboard.argtypes = [w.HWND]
user32.CloseClipboard.restype = w.BOOL
user32.EmptyClipboard.restype = w.BOOL
user32.SetClipboardData.restype = w.HANDLE
user32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
kernel32.GlobalAlloc.restype = w.HGLOBAL
kernel32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [w.HGLOBAL]
kernel32.GlobalUnlock.restype = w.BOOL
kernel32.GlobalUnlock.argtypes = [w.HGLOBAL]

SetWindowsHookExW = user32.SetWindowsHookExW
SetWindowsHookExW.restype = w.HHOOK
SetWindowsHookExW.argtypes = [w.INT, HOOKPROC, w.HINSTANCE, w.DWORD]

UnhookWindowsHookEx = user32.UnhookWindowsHookEx
UnhookWindowsHookEx.restype = w.BOOL
UnhookWindowsHookEx.argtypes = [w.HHOOK]

CallNextHookEx = user32.CallNextHookEx
CallNextHookEx.restype = LRESULT_T
CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]

GetMessageW = user32.GetMessageW
GetMessageW.restype = w.BOOL
GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]

PeekMessageW = user32.PeekMessageW
PeekMessageW.restype = w.BOOL
PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]

DispatchMessageW = user32.DispatchMessageW
DispatchMessageW.restype = w.LPARAM
DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]

PostThreadMessageW = user32.PostThreadMessageW
PostThreadMessageW.restype = w.BOOL
PostThreadMessageW.argtypes = [w.DWORD, w.UINT, w.WPARAM, w.LPARAM]

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.restype = w.HWND

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.restype = w.INT
GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, w.INT]

GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextLengthW.restype = w.INT
GetWindowTextLengthW.argtypes = [w.HWND]

GetCursorPos = user32.GetCursorPos
GetCursorPos.restype = w.BOOL
GetCursorPos.argtypes = [ctypes.POINTER(POINT)]

GetDoubleClickTime = user32.GetDoubleClickTime
GetDoubleClickTime.restype = w.UINT

GetClassNameW = user32.GetClassNameW
GetClassNameW.restype = w.INT
GetClassNameW.argtypes = [w.HWND, w.LPWSTR, w.INT]

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.restype = w.BOOL
SetForegroundWindow.argtypes = [w.HWND]

ShowWindow = user32.ShowWindow
ShowWindow.restype = w.BOOL
ShowWindow.argtypes = [w.HWND, w.INT]

FindWindowW = user32.FindWindowW
FindWindowW.restype = w.HWND
FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.restype = w.BOOL
IsWindowVisible.argtypes = [w.HWND]

SendInput = user32.SendInput
SendInput.restype = w.UINT
SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), w.INT]

GetKeyState = user32.GetKeyState
GetKeyState.restype = w.SHORT
GetKeyState.argtypes = [w.INT]

EnumWindows = user32.EnumWindows
EnumWindows.restype = w.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

# ======================== 键盘模拟 ========================

def _make_input(vk_code: int, keyup: bool = False) -> INPUT:
    """构建单个 SendInput 的 INPUT 结构。"""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk_code
    inp.union.ki.wScan = 0
    inp.union.ki.dwFlags = KEYEVENTF_KEYUP if keyup else 0
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = None
    return inp


def send_key(vk_code: int, modifiers=None):
    """使用 SendInput 发送按键（现代 API，微信不会拦截）。"""
    inputs = []
    if modifiers:
        for mod in modifiers:
            inputs.append(_make_input(mod, keyup=False))
    inputs.append(_make_input(vk_code, keyup=False))
    inputs.append(_make_input(vk_code, keyup=True))
    if modifiers:
        for mod in reversed(modifiers):
            inputs.append(_make_input(mod, keyup=True))

    arr = (INPUT * len(inputs))(*inputs)
    SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    time.sleep(0.02)


def send_ctrl_c():
    """发送 Ctrl+C（复制选中内容）。"""
    send_key(VK_C, [VK_CONTROL])


def send_ctrl_v():
    """发送 Ctrl+V（粘贴）。"""
    send_key(VK_V, [VK_CONTROL])


def send_tab():
    """发送 Tab 键。"""
    send_key(VK_TAB)


def send_enter():
    """发送回车键。"""
    send_key(VK_RETURN)


def type_text(text: str, delay: float = 0.005):
    """逐字符键入文本。优先粘贴整段文本。"""
    _copy_to_clip(text)
    send_ctrl_v()


# ======================== 剪贴板操作 ========================

def _copy_to_clip(text: str):
    """将文本写入剪贴板（内部使用）。"""
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32.OpenClipboard(0)
    user32.EmptyClipboard()
    buf = ctypes.create_unicode_buffer(text)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, (len(text) + 1) * 2)
    ptr = kernel32.GlobalLock(handle)
    ctypes.cdll.msvcrt.wcscpy(ctypes.c_wchar_p(ptr), buf)
    kernel32.GlobalUnlock(handle)
    user32.SetClipboardData(CF_UNICODETEXT, handle)
    user32.CloseClipboard()


# ======================== 窗口工具 ========================

# 微信窗口关键词（标题或类名包含这些即判定为微信）
WECHAT_TITLE_KEYWORDS = ["微信", "WeChat", "Weixin"]
WECHAT_CLASS_KEYWORDS = [
    "WeChatMainWndForPC",
    "ChatWnd",
    "WeChat",
    "mmui::MainWindow",
    "Qt5",
    "CefWebViewWnd",
]


def get_foreground_title() -> str:
    """获取前台窗口标题。"""
    hwnd = GetForegroundWindow()
    if not hwnd:
        return ""
    length = GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def get_foreground_class() -> str:
    """获取前台窗口类名。"""
    hwnd = GetForegroundWindow()
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value if buf.value else ""


def get_foreground_hwnd() -> int:
    """获取前台窗口句柄。"""
    return GetForegroundWindow() or 0


def is_wechat_active() -> bool:
    """判断当前前台窗口是否为微信。"""
    title = get_foreground_title()
    cls = get_foreground_class()

    for kw in WECHAT_TITLE_KEYWORDS:
        if kw.lower() in title.lower():
            return True
    for kw in WECHAT_CLASS_KEYWORDS:
        if kw.lower() in cls.lower():
            return True
    return False


def find_window_by_title(partial_title: str) -> Optional[int]:
    """按标题关键词查找窗口。"""
    result = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        length = GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        if partial_title.lower() in (buf.value or "").lower():
            result.append(hwnd)
        return True

    EnumWindows(callback, 0)
    return result[0] if result else None


def activate_window(hwnd: int) -> bool:
    """激活指定窗口（带到前台）。"""
    if not hwnd:
        return False
    ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.1)
    return bool(SetForegroundWindow(hwnd))


# ======================== 全局鼠标钩子 ========================

class MouseHook:
    """
    全局低级鼠标钩子 — 将左键按下事件放入线程安全队列。

    钩子线程只做「入队」这一件轻量且线程安全的事；
    连击判定 / 复制转储等业务逻辑由主线程消费队列完成，
    避免在钩子回调里执行重逻辑或触发不可重入的 GUI 操作。

    用法:
        hook = MouseHook()
        if hook.start():      # 安装成功
            ev = hook.poll()  # (timestamp, x, y) 或 None
        hook.stop()
    """

    def __init__(self):
        self._hook_id: Optional[int] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._hook_proc = None  # 保持 HOOKPROC 引用存活，防止被 GC
        self._queue: "queue.Queue" = queue.Queue()

    @property
    def installed(self) -> bool:
        """钩子是否已成功安装。"""
        return bool(self._hook_id)

    def start(self) -> bool:
        """启动钩子线程，返回是否安装成功。"""
        if self._running:
            return self.installed
        self._running = True
        self._thread = threading.Thread(target=self._hook_thread, daemon=True)
        self._thread.start()
        time.sleep(0.15)  # 等待钩子安装完成
        return self.installed

    def stop(self) -> None:
        """停止钩子并回收线程。"""
        self._running = False
        if self._thread_id:
            PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def poll(self):
        """非阻塞地取出一个左键按下事件 (timestamp, x, y)，无事件返回 None。"""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def _hook_thread(self) -> None:
        """消息循环线程。"""
        self._thread_id = kernel32.GetCurrentThreadId()

        # 关键：必须先 PeekMessage 创建线程消息队列，再安装钩子
        # 否则 SetWindowsHookExW 返回 ERROR_MOD_NOT_FOUND (126)
        dummy = w.MSG()
        PeekMessageW(ctypes.byref(dummy), 0, 0, 0, PM_NOREMOVE)

        # 安装钩子 — WH_MOUSE_LL 的 hMod 必须为 0 (NULL)
        self._hook_proc = HOOKPROC(self._hook_callback)
        self._hook_id = SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, 0, 0)

        if not self._hook_id:
            err = kernel32.GetLastError()
            print(f"[MouseHook] SetWindowsHookExW 失败! GetLastError={err}")
            if err == 5:
                print("[MouseHook] -> ERROR_ACCESS_DENIED: 请以管理员身份运行")
            elif err == 126:
                print("[MouseHook] -> ERROR_MOD_NOT_FOUND: 消息队列未就绪")
            self._running = False
            return

        print("[MouseHook] 钩子安装成功，开始监听...")

        # Windows 消息循环
        msg = w.MSG()
        while self._running:
            ret = GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if ret <= 0:  # WM_QUIT 或错误
                break
            DispatchMessageW(ctypes.byref(msg))

        # 清理
        if self._hook_id:
            UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None
        self._hook_proc = None

    def _hook_callback(self, nCode: int, wParam: int, lParam: int):
        """钩子回调 — 仅在左键按下时入队，其余消息直接透传。"""
        if nCode == HC_ACTION and wParam == WM_LBUTTONDOWN:
            try:
                p = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                self._queue.put((time.time(), p.pt.x, p.pt.y))
            except Exception:
                traceback.print_exc()
        return CallNextHookEx(self._hook_id, nCode, wParam, lParam)


# ======================== 自检 ========================

if __name__ == "__main__":
    if sys.platform != "win32":
        print("hook_engine 仅在 Windows 上可用")
        sys.exit(0)

    print("=== 窗口检测测试 ===")
    print(f"前台窗口: {get_foreground_title()}")
    print(f"类名: {get_foreground_class()}")
    print(f"是微信?: {is_wechat_active()}")

    print("\n=== 键盘模拟测试（3秒后执行）===")
    print("请在 3 秒内打开一个文本编辑器...")
    time.sleep(3)
    _copy_to_clip("测试文本 — 来自 hook_engine")
    send_ctrl_v()
    print("已粘贴!")
