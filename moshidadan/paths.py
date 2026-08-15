"""
产地快打 — 应用路径解析

统一处理「源码运行」与「PyInstaller 打包（onefile）」两种场景下的路径：
  - 源码运行：__file__ 所在目录即应用目录
  - 打包后：__file__ 指向临时解压目录 _MEIPASS（退出即被清理），
            因此数据类路径（config / logs / 数据文件）必须改用 exe 所在目录。

典型用法:
    from paths import app_dir, resource_path

    config_path = os.path.join(app_dir(), "config.json")     # 可写数据
    icon_path   = resource_path("icon.ico")                  # 只读资源（打包内）
"""

import os
import sys


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的可执行文件中。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """返回应用数据目录（配置 / 日志 / 数据文件应写入此目录）。

    打包后返回 exe 所在目录，避免写入临时 _MEIPASS 目录导致数据丢失。
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative: str) -> str:
    """返回只读资源文件的绝对路径。

    onefile 下资源被解压到 _MEIPASS 临时目录，需从此处读取；
    源码运行时直接从源码目录读取。
    """
    if is_frozen():
        base = getattr(sys, "_MEIPASS", app_dir())
        return os.path.join(base, relative)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)
