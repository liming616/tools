"""
产地快打 — 单实例互斥模块

使用 Windows 命名 Mutex 阻止第二个实例重复启动。
"""

import ctypes
import ctypes.wintypes as w
import sys
from typing import Optional

SINGLE_INSTANCE_MUTEX_NAME = "Local\\ChanDiKuaiDa.SingleInstance"
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance(
    name: str = SINGLE_INSTANCE_MUTEX_NAME,
) -> Optional[int]:
    """尝试获取单实例互斥锁。

    Args:
        name: 互斥锁名称，默认使用全局统一的单实例名称。

    Returns:
        成功返回句柄（进程存活期间保持打开即可）；
        已有实例在运行或创建失败时返回 None。
    """
    if sys.platform != "win32":
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = w.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    kernel32.CloseHandle.restype = w.BOOL
    kernel32.CloseHandle.argtypes = [w.HANDLE]

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None

    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)
