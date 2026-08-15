"""
快速验证钩子安装是否成功。
独立于 diagnose.py，只测试 PeekMessage + SetWindowsHookExW 流程。
"""
import ctypes
import ctypes.wintypes as w
import threading
import time

WH_MOUSE_LL = 14
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class POINT(ctypes.Structure):
    _fields_ = [('x', w.LONG), ('y', w.LONG)]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('pt', POINT), ('mouseData', w.DWORD),
        ('flags', w.DWORD), ('time', w.DWORD),
        ('dwExtraInfo', ctypes.POINTER(w.ULONG)),
    ]

HOOKPROC = ctypes.WINFUNCTYPE(w.LPARAM, w.INT, w.WPARAM, ctypes.POINTER(MSLLHOOKSTRUCT))

user32.PeekMessageW.restype = w.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]

user32.SetWindowsHookExW.restype = w.HHOOK
user32.SetWindowsHookExW.argtypes = [w.INT, HOOKPROC, w.HINSTANCE, w.DWORD]

user32.UnhookWindowsHookEx.restype = w.BOOL
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]

user32.GetMessageW.restype = w.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]

user32.DispatchMessageW.restype = w.LPARAM
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]

hook_id = [None]
clicks = []

def hook_proc(nCode, wParam, lParam):
    if nCode >= 0 and wParam == 0x0201:  # WM_LBUTTONDOWN
        clicks.append(1)
    return user32.CallNextHookEx(hook_id[0], nCode, wParam, lParam) if hook_id[0] else 0

def hook_thread():
    tid = kernel32.GetCurrentThreadId()
    print(f"  线程 ID: {tid}")

    # Step 1: PeekMessage creates message queue
    dummy = w.MSG()
    user32.PeekMessageW(ctypes.byref(dummy), 0, 0, 0, 0)
    print("  [1/3] PeekMessage OK")

    # Step 2: Install hook
    cb = HOOKPROC(hook_proc)
    hook_id[0] = user32.SetWindowsHookExW(WH_MOUSE_LL, cb, 0, 0)
    if not hook_id[0]:
        err = kernel32.GetLastError()
        print(f"  [2/3] FAIL! GetLastError={err}")
        return False
    print(f"  [2/3] Hook installed: {hook_id[0]}")

    # Step 3: Message loop
    print("  [3/3] Message loop running (3s)...")
    msg = w.MSG()
    start = time.time()
    while time.time() - start < 3:
        ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
        if ret <= 0:
            break
        user32.DispatchMessageW(ctypes.byref(msg))

    user32.UnhookWindowsHookEx(hook_id[0])
    print(f"  Done. Clicks captured: {len(clicks)}")
    return True

print("=== Hook Installation Test ===")
t = threading.Thread(target=hook_thread, daemon=True)
t.start()
t.join(10)
if t.is_alive():
    print("TIMEOUT")
else:
    print("PASS")
