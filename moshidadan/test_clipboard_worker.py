"""ClipboardWorker 单元测试。"""
import time
import unittest
from unittest.mock import patch

import clipboard_worker


class ClipboardWorkerTest(unittest.TestCase):
    """覆盖: 后台读取 / 阻塞不卡主线程 / 写入成功 / 写入超时 / 等待变化。"""

    def test_get_latest_returns_empty_before_start(self):
        worker = clipboard_worker.ClipboardWorker()
        self.assertEqual(worker.get_latest_text(), "")

    def test_worker_reads_latest_text_in_background(self):
        worker = clipboard_worker.ClipboardWorker(read_interval_ms=20, read_timeout_ms=50)
        with patch("clipboard_worker.safe_read_clipboard", return_value="测试文本"):
            worker.start()
            try:
                deadline = time.time() + 2
                while time.time() < deadline:
                    if worker.get_latest_text() == "测试文本":
                        break
                    time.sleep(0.02)
                self.assertEqual(worker.get_latest_text(), "测试文本")
            finally:
                worker.stop()

    def test_blocked_read_does_not_block_main_thread(self):
        worker = clipboard_worker.ClipboardWorker(read_interval_ms=50, read_timeout_ms=50)

        def blocked(timeout_ms):
            time.sleep(1.0)
            return "晚到文本"

        with patch("clipboard_worker.safe_read_clipboard", side_effect=blocked):
            worker.start()
            try:
                t0 = time.time()
                text = worker.get_latest_text()
                elapsed = time.time() - t0
                self.assertEqual(text, "")
                self.assertLess(elapsed, 0.5)
            finally:
                worker.stop()

    def test_write_clipboard_returns_true(self):
        worker = clipboard_worker.ClipboardWorker()
        worker.start()
        try:
            with patch("clipboard_worker.safe_write_clipboard", return_value=True) as mock_write:
                self.assertTrue(worker.write_clipboard("text", timeout_ms=1000))
                mock_write.assert_called_once_with("text")
        finally:
            worker.stop()

    def test_write_timeout_returns_false_when_worker_stuck(self):
        worker = clipboard_worker.ClipboardWorker()

        def stuck_write(text):
            time.sleep(1.5)
            return True

        worker.start()
        try:
            with patch("clipboard_worker.safe_write_clipboard", side_effect=stuck_write):
                self.assertFalse(worker.write_clipboard("text", timeout_ms=300))
        finally:
            worker.stop()

    def test_wait_for_change_returns_new_text(self):
        worker = clipboard_worker.ClipboardWorker(read_interval_ms=20, read_timeout_ms=50)
        values = ["旧文本", "新文本"]
        state = {"i": 0}

        def fake_read(timeout_ms):
            text = values[min(state["i"], len(values) - 1)]
            state["i"] += 1
            return text

        with patch("clipboard_worker.safe_read_clipboard", side_effect=fake_read):
            worker.start()
            try:
                deadline = time.time() + 2
                while time.time() < deadline:
                    if worker.get_latest_text() == "旧文本":
                        break
                    time.sleep(0.02)
                result = worker.wait_for_change("旧文本", timeout_ms=1000, poll_interval_ms=20)
                self.assertEqual(result, "新文本")
            finally:
                worker.stop()


if __name__ == "__main__":
    unittest.main()
