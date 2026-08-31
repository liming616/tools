"""
产地快打剪贴板卡死复现工具（不修改应用代码）

原理：
  用延迟渲染方式占用剪贴板，并故意拖延 WM_RENDERFORMAT 的响应，
  让调用 GetClipboardData 的进程在主线程上长时间等待。

用法：
  1. 先启动 产地快打
  2. 另开一个终端运行本脚本
  3. 在任意程序复制文本，或等软件下一轮剪贴板轮询
  4. 观察软件窗口是否冻结、logs/moshidadan.log 心跳是否中断
"""
import ctypes
import ctypes.wintypes as w
import sys
import time

CF_UNICODETEXT = 13
WM_RENDERFORMAT = 0x0305
RENDER_DELAY = 30  # 模拟占用秒数；改大可接近“永久卡死”

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", w.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", w.HINSTANCE),
        ("hIcon", w.HICON),
        ("hCursor", w.HCURSOR),
        ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR),
    ]


user32.RegisterClassW.restype = ctypes.c_ushort
user32.CreateWindowExW.restype = w.HWND
user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
user32.OpenClipboard.restype = w.BOOL
user32.OpenClipboard.argtypes = [w.HWND]
user32.EmptyClipboard.restype = w.BOOL
user32.SetClipboardData.restype = w.HANDLE
user32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
user32.CloseClipboard.restype = w.BOOL
user32.GetMessageW.restype = w.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.TranslateMessage.restype = w.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
kernel32.GetModuleHandleW.restype = w.HMODULE
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GlobalAlloc.restype = w.HGLOBAL
kernel32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [w.HGLOBAL]
kernel32.GlobalUnlock.restype = w.BOOL
kernel32.GlobalUnlock.argtypes = [w.HGLOBAL]


def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_RENDERFORMAT:
        print(f"[repro] 收到渲染请求，模拟剪贴板所有者忙 {RENDER_DELAY}s...", flush=True)
        time.sleep(RENDER_DELAY)
        text = "产地快打延迟渲染复现文本"
        buf = ctypes.create_unicode_buffer(text)
        handle = kernel32.GlobalAlloc(0x0002, (len(text) + 1) * 2)
        ptr = kernel32.GlobalLock(handle)
        ctypes.cdll.msvcrt.wcscpy(ctypes.c_wchar_p(ptr), buf)
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        print("[repro] 渲染完成，剪贴板已释放", flush=True)
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    wc = WNDCLASS()
    wc.lpfnWndProc = WNDPROC(wnd_proc)
    wc.lpszClassName = "ClipboardDelayRepro"
    wc.hInstance = kernel32.GetModuleHandleW(None)
    if not user32.RegisterClassW(ctypes.byref(wc)):
        print("[repro] 窗口类注册失败", flush=True)
        return 1
    hwnd = user32.CreateWindowExW(0, "ClipboardDelayRepro", "repro", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, 0)
    if not user32.OpenClipboard(hwnd):
        print("[repro] 打开剪贴板失败", flush=True)
        return 1
    user32.EmptyClipboard()
    # NULL 句柄表示延迟渲染；返回 0 是正常表现，不要按失败处理
    user32.SetClipboardData(CF_UNICODETEXT, None)
    user32.CloseClipboard()
    print("[repro] 剪贴板已设为延迟渲染，等待读取；Ctrl+C 退出", flush=True)
    msg = w.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        print("[repro] 退出", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())


