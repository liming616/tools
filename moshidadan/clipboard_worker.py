"""
产地快打 — 剪贴板工作线程模块

将剪贴板 WinAPI 调用从 Tk 主线程移出到独立 daemon 线程：
  - 后台持续读取剪贴板，主线程只读取最新快照，不再直接调用 WinAPI
  - 写入请求放入队列，由工作线程执行，主线程带超时等待结果
  - 即使剪贴板所有者长时间不响应，主线程也不会被永久卡死
"""

import queue
import threading
import time
from typing import Optional

from clipboard_safe import (
    get_clipboard_sequence,
    safe_read_clipboard,
    safe_write_clipboard,
)


class ClipboardWorker:
    """后台剪贴板读写线程。"""

    def __init__(self, read_interval_ms: int = 300, read_timeout_ms: int = 500):
        self._read_interval = read_interval_ms / 1000.0
        self._read_timeout_ms = read_timeout_ms
        self._latest_text = ""
        self._latest_ts = 0.0
        self._last_sequence: Optional[int] = None
        self._lock = threading.Lock()
        self._write_queue: "queue.Queue" = queue.Queue()
        self._write_results: dict[int, bool] = {}
        self._write_lock = threading.Lock()
        self._next_write_id = 1
        self._id_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """启动后台工作线程（幂等）。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="clipboard-worker"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止工作线程（最多等待 2 秒）。"""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_latest_text(self) -> str:
        """返回最近一次读取到的剪贴板文本（非阻塞）。"""
        with self._lock:
            return self._latest_text

    def get_latest_ts(self) -> float:
        """返回最近一次成功读取的时间戳（非阻塞）。"""
        with self._lock:
            return self._latest_ts

    def is_stale(self, max_age_sec: float) -> bool:
        """判断最近一次剪贴板读取是否已超过指定时长。"""
        ts = self.get_latest_ts()
        if ts <= 0:
            return True
        return (time.time() - ts) > max_age_sec

    def write_clipboard(self, text: str, timeout_ms: int = 2000) -> bool:
        """提交写入请求并等待结果；超时返回 False，不会永久阻塞主线程。"""
        req_id = self._request_write(text)
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            result = self._get_write_result(req_id)
            if result is not None:
                return result
            time.sleep(0.02)
        return False

    def wait_for_change(
        self,
        prev_seq: Optional[int],
        timeout_ms: int = 500,
        poll_interval_ms: int = 50,
    ) -> Optional[str]:
        """等待工作线程读取到新的剪贴板序列号。

        不做文本去重：只要剪贴板序列号变化（发生新复制），即使内容与上次相同也返回。
        仅轮询内存中的快照，不调用剪贴板 WinAPI，因此不会卡死主线程。
        """
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            if self.get_latest_sequence() != prev_seq:
                text = self.get_latest_text()
                if text and text.strip():
                    return text
            time.sleep(poll_interval_ms / 1000.0)
        return None

    def _request_write(self, text: str) -> int:
        """生成写入请求 ID 并放入队列。"""
        with self._id_lock:
            req_id = self._next_write_id
            self._next_write_id += 1
        self._write_queue.put((req_id, text))
        return req_id

    def _get_write_result(self, req_id: int) -> Optional[bool]:
        """非阻塞读取写入结果；未完成时返回 None。"""
        with self._write_lock:
            if req_id in self._write_results:
                return self._write_results[req_id]
        return None

    def _loop(self) -> None:
        """工作线程主循环：先处理写入，再按剪贴板序列号变化读取快照。"""
        while self._running:
            try:
                req_id, text = self._write_queue.get_nowait()
            except queue.Empty:
                req_id = None
                text = None

            if req_id is not None:
                ok = safe_write_clipboard(text)
                with self._write_lock:
                    self._write_results[req_id] = ok
                # 写入会改变剪贴板序列号，强制下一轮重读一次
                with self._lock:
                    self._last_sequence = None

            current_seq = get_clipboard_sequence()
            if current_seq != self._last_sequence:
                # 仅在剪贴板变化后抢读；失败时保留旧快照与旧序列号，下一轮继续重试
                current = safe_read_clipboard(timeout_ms=self._read_timeout_ms)
                if current is not None:
                    with self._lock:
                        self._latest_text = current
                        self._latest_ts = time.time()
                        self._last_sequence = current_seq

            time.sleep(self._read_interval)

    def get_latest_sequence(self) -> Optional[int]:
        """返回最近一次成功读取的剪贴板序列号（非阻塞，None 表示尚未读取）。"""
        with self._lock:
            return self._last_sequence
