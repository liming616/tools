"""剪贴板预览区单行规范化与去重逻辑的单元测试。"""
import unittest
from unittest import mock

import main as main_mod
from main import App


def make_preview_app():
    """构造仅含预览区写入逻辑所需属性的 App 实例。"""
    app = App.__new__(App)
    content = ""
    preview = mock.Mock()

    def fake_get(*args, **kwargs):
        return content

    def fake_insert(index, text, *args, **kwargs):
        nonlocal content
        if index == "1.0":
            content = text + content
        else:
            content += text

    preview.get.side_effect = fake_get
    preview.insert.side_effect = fake_insert
    app._preview_text = preview
    app._preview_info_var = mock.Mock()
    app._transfer_btn = mock.Mock()
    app._source_var = mock.Mock()
    return app, lambda: content


class PreviewNormalizeTest(unittest.TestCase):
    """覆盖：剪贴板文本写入预览区前被规范化为单行。"""

    def test_normalize_join_consecutive_newlines_to_one_space(self):
        self.assertEqual(
            App._normalize_clipboard_text("  张三\r\n13800000000\n\n广东省深圳市  "),
            "张三 13800000000 广东省深圳市",
        )

    def test_normalize_keeps_inner_spaces(self):
        self.assertEqual(
            App._normalize_clipboard_text(" 张三  13800000000 "),
            "张三  13800000000",
        )

    def test_normalize_empty_text(self):
        self.assertEqual(App._normalize_clipboard_text("  \n  "), "")
        self.assertEqual(App._normalize_clipboard_text(""), "")

    def test_set_preview_writes_normalized_first_line(self):
        app, get_content = make_preview_app()
        with mock.patch.object(main_mod, "get_foreground_title", return_value="测试窗口"):
            app._set_preview("  张三\n13800000000\r\n广东省深圳市  ")
        self.assertEqual(get_content(), "张三 13800000000 广东省深圳市")

    def test_set_preview_appends_multiple_copies_as_lines(self):
        app, get_content = make_preview_app()
        with mock.patch.object(main_mod, "get_foreground_title", return_value=""):
            app._set_preview("第一行\n内容")
            app._set_preview("第二行")
        self.assertEqual(get_content(), "第一行 内容\n第二行")

    def test_set_preview_skips_blank_text(self):
        app, get_content = make_preview_app()
        with mock.patch.object(main_mod, "get_foreground_title", return_value=""):
            app._set_preview("  \n  ")
        self.assertEqual(get_content(), "")
        app._preview_text.insert.assert_not_called()


class PollClipboardNormalizeTest(unittest.TestCase):
    """覆盖：轮询时按规范化后的文本进行去重。"""

    def make_app(self, last_clipboard):
        app = App.__new__(App)
        app._running = True
        app._last_poll_time = 0.0
        app._poll_count = 0
        app._last_clipboard = last_clipboard
        app._degraded = False
        app._dc_paused = False
        app._auto_var = mock.Mock()
        app._auto_var.get.return_value = False
        app._preview_text = mock.Mock()
        app._preview_text.get.return_value = ""
        app._root = mock.Mock()
        app._error_timestamps = []
        app.config = {"poll_interval_ms": 400}
        app._safe_read_clipboard = mock.Mock()
        app._set_preview = mock.Mock()
        app._transfer = mock.Mock()
        app._check_recovery = mock.Mock()
        app._record_error = mock.Mock()
        return app

    def test_same_normalized_text_is_skipped(self):
        app = self.make_app(last_clipboard="张三 13800000000")
        app._safe_read_clipboard.return_value = " 张三\n13800000000 "
        app._poll_clipboard()
        app._set_preview.assert_not_called()

    def test_different_normalized_text_updates_preview(self):
        app = self.make_app(last_clipboard="张三 13800000000")
        app._safe_read_clipboard.return_value = "李四\n13900000000"
        app._poll_clipboard()
        app._set_preview.assert_called_once_with("李四 13900000000")


if __name__ == "__main__":
    unittest.main()
