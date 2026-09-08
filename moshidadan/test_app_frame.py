"""主窗口纯逻辑方法单元测试（不触发 Tk 主循环）。"""
import os
import sys
import unittest
from unittest import mock
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_frame as app_frame_mod
from app_frame import AppFrame, WIDE_COLUMN_WIDTHS


class AppFrameLogicTest(unittest.TestCase):
    def test_build_row_serial(self):
        frame = AppFrame.__new__(AppFrame)
        frame._list_headers = ["序号", "收件人姓名", "收件人手机"]
        row = frame.build_row({"name": "张三", "phone": "13800138000"}, serial=1)
        self.assertEqual(row, ("☐", "1", "张三", "13800138000"))

    def test_build_row_includes_select_column_selected(self):
        frame = AppFrame.__new__(AppFrame)
        frame._list_headers = ["序号", "收件人姓名"]
        row = frame.build_row({"name": "张三"}, serial=1, selected=True)
        self.assertEqual(row, ("☑", "1", "张三"))

    def test_update_select_header_all_checked(self):
        frame = AppFrame.__new__(AppFrame)
        frame._tree = mock.MagicMock()
        frame._tree.get_children.return_value = ["i1", "i2"]
        frame._tree.set.return_value = "☑"
        frame.update_select_header()
        frame._tree.heading.assert_called_with("选择", text="☑")

    def test_update_select_header_none_checked(self):
        frame = AppFrame.__new__(AppFrame)
        frame._tree = mock.MagicMock()
        frame._tree.get_children.return_value = ["i1", "i2"]
        frame._tree.set.return_value = "☐"
        frame.update_select_header()
        frame._tree.heading.assert_called_with("选择", text="☐")

    def test_get_focus_target_uses_tracked_value(self):
        frame = AppFrame.__new__(AppFrame)
        frame._focus_target = "sender"
        self.assertEqual(frame.get_focus_target(), "sender")
        frame._focus_target = "receiver"
        self.assertEqual(frame.get_focus_target(), "receiver")
        frame._focus_target = ""
        self.assertEqual(frame.get_focus_target(), "")

    def test_mark_focus_target(self):
        frame = AppFrame.__new__(AppFrame)
        frame._focus_target = ""
        frame._mark_focus_target("sender")
        self.assertEqual(frame._focus_target, "sender")
        frame._mark_focus_target("receiver")
        self.assertEqual(frame._focus_target, "receiver")

    def test_get_tree_columns(self):
        frame = AppFrame.__new__(AppFrame)
        frame._list_headers = ["序号", "收件人姓名"]
        self.assertEqual(frame.get_tree_columns(), ("序号", "收件人姓名"))

    def test_apply_template_widens_address_columns(self):
        """回归：地址类列固定加宽，其余列 stretch 填满。"""
        frame = AppFrame.__new__(AppFrame)
        frame._app_config = {}
        frame._tree = mock.MagicMock()
        frame._tree.get_children.return_value = []
        headers = ["序号", "收货人", "联系方式",
                   "详细地址(省+市+区/县+街道号+门牌号)", "产品类型"]
        with mock.patch.object(app_frame_mod, "get_list_headers", return_value=headers):
            frame._apply_template("JD_OFFICIAL")
        wide_col = "详细地址(省+市+区/县+街道号+门牌号)"
        wide_width = WIDE_COLUMN_WIDTHS[wide_col]
        # 地址列固定加宽、不拉伸
        frame._tree.column.assert_any_call(
            wide_col, width=wide_width, anchor=tk.W, stretch=False)
        # 普通列保持默认 120、stretch=True
        frame._tree.column.assert_any_call(
            "收货人", width=120, anchor=tk.W, stretch=False)


if __name__ == "__main__":
    unittest.main()
