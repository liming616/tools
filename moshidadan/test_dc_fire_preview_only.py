"""连击触发（双击/三击）复制到预览区、不直接转储的单元测试。"""
import time
import unittest
from unittest import mock

import main as main_mod
from main import App


def make_app():
    """构造仅含 _dc_fire 逻辑所需属性的 App 实例。"""
    app = App.__new__(App)
    app._dc_fire_id = None
    app._running = True
    app._dc_enabled = True
    app._dc_paused = False
    app._dc_cooldown_until = 0.0
    app._dc_cooldown_s = 0.8
    app._dc_click_count = 0
    app._dc_history = []
    app._mouse_last_x = 0
    app._mouse_last_y = 0
    app._last_clipboard = "旧文本"
    app._set_preview = mock.Mock()
    app._transfer = mock.Mock()
    app._flash_status = mock.Mock()
    app._capture_with_retry = mock.Mock()
    return app


class DcFirePreviewOnlyTest(unittest.TestCase):
    """覆盖：连击成功后只写预览区、不转储列表；失败与冷却分支不受影响。"""

    def test_success_writes_preview_without_transfer(self):
        app = make_app()
        app._capture_with_retry.return_value = "新文本"
        app._dc_fire()
        self.assertEqual(app._last_clipboard, "新文本")
        app._set_preview.assert_called_once_with("新文本")
        app._transfer.assert_not_called()
        app._flash_status.assert_called_once()

    def test_failure_shows_hint_without_transfer(self):
        app = make_app()
        app._capture_with_retry.return_value = None
        with mock.patch.object(main_mod, "get_foreground_title", return_value="测试窗口"):
            app._dc_fire()
        app._set_preview.assert_not_called()
        app._transfer.assert_not_called()
        app._flash_status.assert_called_once()

    def test_cooldown_skips_capture(self):
        app = make_app()
        app._dc_cooldown_until = time.time() + 5
        app._dc_fire()
        app._capture_with_retry.assert_not_called()
        app._set_preview.assert_not_called()
        app._transfer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
