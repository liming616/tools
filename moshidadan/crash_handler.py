"""
产地快打 — 全局异常处理与崩溃恢复

特性:
  - 捕获未处理异常，写入崩溃日志
  - 显示友好的错误对话框
  - 保护轮询循环永不中断
  - 错误计数与自动暂停机制
"""

import sys
import os
import time
import threading
import traceback
from typing import Callable, Optional

from paths import app_dir

# ======================== 崩溃日志 ========================

CRASH_LOG_DIR = os.path.join(app_dir(), "logs")


def _ensure_crash_dir() -> None:
    try:
        os.makedirs(CRASH_LOG_DIR, exist_ok=True)
    except Exception:
        pass


def write_crash_report(exc_type, exc_value, exc_tb) -> str:
    """
    将崩溃信息写入文件，返回文件路径。
    """
    _ensure_crash_dir()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    crash_file = os.path.join(CRASH_LOG_DIR, f"crash_{timestamp}.log")

    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_text = "".join(tb_lines)

    try:
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write(f"崩溃时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Python 版本: {sys.version}\n")
            f.write(f"平台: {sys.platform}\n")
            f.write(f"工作目录: {os.getcwd()}\n")
            f.write("-" * 60 + "\n")
            f.write(tb_text)
            f.write("-" * 60 + "\n")
            # 线程信息
            f.write(f"\n活跃线程数: {threading.active_count()}\n")
            for t in threading.enumerate():
                f.write(f"  {t.name} (daemon={t.daemon})\n")
        return crash_file
    except Exception:
        return ""


def install_crash_handler(on_crash: Optional[Callable[[str], None]] = None) -> None:
    """
    安装全局异常处理器。

    Args:
        on_crash: 崩溃后的回调，接收崩溃日志文件路径
    """

    def _handler(exc_type, exc_value, exc_tb):
        # 跳过 KeyboardInterrupt（用户主动退出）
        if exc_type is KeyboardInterrupt:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        # 写入崩溃文件
        crash_path = write_crash_report(exc_type, exc_value, exc_tb)

        # 打印到 stderr
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(f"\n[产地快打] 发生未处理异常:\n{tb_text}\n")
        if crash_path:
            sys.stderr.write(f"[产地快打] 崩溃日志已保存至: {crash_path}\n")

        # 回调
        if on_crash:
            try:
                on_crash(crash_path)
            except Exception:
                pass

        # 调用原始 hook
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _handler

    # 同时处理线程内的异常
    original_thread_init = threading.Thread.__init__

    def _patched_init(self, *args, **kwargs):
        original_thread_init(self, *args, **kwargs)
        original_run = self.run

        def _patched_run():
            try:
                original_run()
            except Exception as e:
                _handler(type(e), e, e.__traceback__)

        self.run = _patched_run

    threading.Thread.__init__ = _patched_init


# ======================== 轮询安全装饰器 ========================


def safe_poll(logger, max_errors_per_minute: int = 10):
    """
    装饰器：保护轮询回调，使其永不被异常中断。

    特性:
      - 异常时自动 logging
      - 错误率过高时暂停轮询（防止日志洪泛）
      - 返回 True 表示调用成功，False 表示异常

    Usage:
        @safe_poll(logger)
        def _poll_clipboard(self):
            ...
    """
    errors = []
    paused_until = [0.0]

    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            nonlocal errors, paused_until

            now = time.time()

            # 清除 1 分钟前的错误记录
            errors[:] = [t for t in errors if now - t < 60]

            # 如果错误过多，暂停
            if len(errors) >= max_errors_per_minute:
                if paused_until[0] == 0:
                    paused_until[0] = now + 30
                    logger.error(
                        "轮询错误过多（%d次/分钟），暂停 30 秒", len(errors)
                    )
                if now < paused_until[0]:
                    return False
                else:
                    # 恢复
                    paused_until[0] = 0
                    errors.clear()
                    logger.info("轮询恢复")

            try:
                func(*args, **kwargs)
                return True
            except Exception as e:
                errors.append(now)
                logger.error(
                    "轮询异常 (%d/%d): %s",
                    len(errors), max_errors_per_minute, e,
                )
                return False

        return wrapper

    return decorator


# ======================== 友好错误对话框 ========================


def show_error_dialog(title: str, message: str, detail: str = "") -> bool:
    """
    显示友好的错误对话框（中文）。

    优先使用 tkinter messagebox，不可用时回退到控制台。

    Returns:
        True 如果用户点击了"确定"
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        # 确保有 root
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()

        full_msg = message
        if detail:
            full_msg += f"\n\n详细信息:\n{detail}"

        return messagebox.showerror(title, full_msg)
    except Exception:
        # 回退到控制台
        sys.stderr.write(f"\n[{title}]\n{message}\n")
        if detail:
            sys.stderr.write(f"详细信息: {detail}\n")
        return False


def show_warning_dialog(title: str, message: str) -> bool:
    """显示警告对话框。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()

        return messagebox.showwarning(title, message)
    except Exception:
        sys.stderr.write(f"\n[警告] {title}: {message}\n")
        return False
