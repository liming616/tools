"""
产地快打 — 生产级日志系统

特性:
  - 按日期自动轮转 (RotatingFileHandler)
  - 多级别: DEBUG / INFO / WARNING / ERROR / CRITICAL
  - 结构化日志格式，含时间戳、级别、模块、行号
  - 自动清理超过保留期的旧日志
  - 异常 traceback 自动记录
  - 控制台 + 文件双输出
  - 线程安全
"""

import logging
import logging.handlers
import os
import sys
import time
import traceback
from datetime import datetime
from typing import Optional

from paths import app_dir

# ======================== 常量 ========================

LOG_DIR = os.path.join(app_dir(), "logs")
LOG_FILE = os.path.join(LOG_DIR, "moshidadan.log")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB 单文件上限
LOG_BACKUP_COUNT = 10  # 保留最近 10 个备份
LOG_RETENTION_DAYS = 30  # 超过 30 天的日志自动删除

# ======================== 单例 ========================

_root_logger: Optional[logging.Logger] = None
_start_time: Optional[str] = None


def _ensure_log_dir() -> None:
    """确保日志目录存在。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        pass


def _cleanup_old_logs() -> None:
    """删除超过保留期的旧日志文件。"""
    if not os.path.isdir(LOG_DIR):
        return
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    try:
        for fname in os.listdir(LOG_DIR):
            if not fname.endswith(".log") and not fname.endswith(".log.gz"):
                continue
            fpath = os.path.join(LOG_DIR, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
            except OSError:
                pass
    except Exception:
        pass


def get_logger(name: str = "moshidadan") -> logging.Logger:
    """
    获取或创建 logger 实例。

    Args:
        name: logger 名称，默认为 "moshidadan"。
              子模块使用 "moshidadan.parser" 等分层命名。

    Returns:
        logging.Logger 实例
    """
    global _root_logger, _start_time

    if _root_logger is None:
        _ensure_log_dir()
        _cleanup_old_logs()
        _start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        _root_logger = logging.getLogger("moshidadan")
        _root_logger.setLevel(logging.DEBUG)

        # 控制台输出（INFO 及以上）
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            LOG_DATE_FORMAT,
        ))
        _root_logger.addHandler(console)

        # 文件输出（DEBUG 及以上，带轮转）
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                LOG_FILE,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                LOG_FORMAT, LOG_DATE_FORMAT,
            ))
            _root_logger.addHandler(file_handler)
        except Exception:
            # 文件日志不可用时至少保留控制台输出
            _root_logger.warning("无法创建日志文件: %s", LOG_FILE)

        # 写入启动标记
        _root_logger.info("=" * 50)
        _root_logger.info("产地快打 启动 — %s", _start_time)
        _root_logger.info("日志目录: %s", LOG_DIR)
        _root_logger.info("Python: %s | 平台: %s", sys.version.split()[0], sys.platform)
        _root_logger.info("=" * 50)

    return _root_logger.getChild(name.split(".")[-1]) if name != "moshidadan" else _root_logger


def log_exception(logger: logging.Logger, e: Exception, context: str = "") -> None:
    """
    记录异常的完整 traceback。

    Args:
        logger: logger 实例
        e: 异常对象
        context: 额外的上下文描述
    """
    tb = traceback.format_exc()
    if context:
        logger.error("%s — %s: %s\n%s", context, type(e).__name__, e, tb)
    else:
        logger.error("%s: %s\n%s", type(e).__name__, e, tb)


def get_log_dir() -> str:
    """返回日志目录路径（供诊断使用）。"""
    _ensure_log_dir()
    return LOG_DIR


def get_log_file() -> str:
    """返回当前日志文件路径。"""
    _ensure_log_dir()
    return LOG_FILE
