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

    def test_build_row_displays_weight_for_official_header(self):
        """京东散单重量列应显示 weight 字段值。"""
        frame = AppFrame.__new__(AppFrame)
        frame._list_headers = ["序号", "重量（kg）"]
        row = frame.build_row({"weight": "1"}, serial=1)
        self.assertEqual(row, ("☐", "1", "1"))

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


    def test_sender_focus_selects_group1_when_none_selected(self):
        """回归：无有效寄件人组时，聚焦寄件文本框应默认绑定寄件人1。"""
        frame = AppFrame.__new__(AppFrame)
        frame._config = {}
        frame._sender_sel = mock.Mock()
        frame._sender_sel.get.return_value = ""
        frame._sender_buttons = {
            "寄件人1": mock.Mock(),
            "寄件人2": mock.Mock(),
            "寄件人3": mock.Mock(),
        }
        frame._load_sender_texts = mock.Mock()
        frame._mark_focus_target = mock.Mock()

        frame._on_sender_focus()

        frame._mark_focus_target.assert_called_once_with("sender")
        frame._sender_sel.set.assert_called_once_with("寄件人1")
        self.assertEqual(frame._config["selected_sender"], "寄件人1")
        frame._sender_buttons["寄件人1"].configure.assert_called_once_with(
            style="TabActive.TButton"
        )
        frame._load_sender_texts.assert_called_once_with("寄件人1")

    def test_sender_focus_keeps_existing_valid_group(self):
        """回归：已有有效寄件人组时，聚焦寄件文本框不得切换或重载。"""
        frame = AppFrame.__new__(AppFrame)
        frame._config = {"selected_sender": "寄件人2"}
        frame._sender_sel = mock.Mock()
        frame._sender_sel.get.return_value = "寄件人2"
        frame._sender_buttons = {
            "寄件人1": mock.Mock(),
            "寄件人2": mock.Mock(),
            "寄件人3": mock.Mock(),
        }
        frame._load_sender_texts = mock.Mock()
        frame._mark_focus_target = mock.Mock()

        frame._on_sender_focus()

        frame._mark_focus_target.assert_called_once_with("sender")
        frame._sender_sel.set.assert_not_called()
        frame._load_sender_texts.assert_not_called()

    def test_sender_selection_saves_current_group_before_switching(self):
        """回归：手动切换寄件人组时，仍先保存旧组再加载新组。"""
        frame = AppFrame.__new__(AppFrame)
        frame._config = {"selected_sender": "寄件人1"}
        frame._sender_sel = mock.Mock()
        frame._sender_buttons = {
            "寄件人1": mock.Mock(),
            "寄件人2": mock.Mock(),
            "寄件人3": mock.Mock(),
        }
        frame._save_current_sender_texts = mock.Mock()
        frame._load_sender_texts = mock.Mock()

        frame._on_sender_selected("寄件人2")

        frame._save_current_sender_texts.assert_called_once()
        frame._sender_sel.set.assert_called_once_with("寄件人2")
        frame._load_sender_texts.assert_called_once_with("寄件人2")

    def test_sender_paste_replaces_selected_text_only(self):
        """回归：寄件人框有选区时，粘贴只替换选区并保留其他内容。"""
        root = tk.Tk()
        root.withdraw()
        try:
            sender_text = tk.Text(root)
            sender_text.insert("1.0", "张三 13800138000 北京")
            sender_text.tag_add("sel", "1.3", "1.14")
            sender_text.mark_set("insert", "1.14")

            frame = AppFrame.__new__(AppFrame)
            frame._sender_text = sender_text
            frame.clipboard_get = mock.Mock(return_value="13900139000")

            frame._on_sender_paste()

            self.assertEqual(
                sender_text.get("1.0", "end-1c"),
                "张三 13900139000 北京",
            )
        finally:
            root.destroy()

    def test_sender_paste_without_selection_still_overwrites_sender_text(self):
        """回归：寄件人框无选区时，保持原有整段覆盖行为。"""
        root = tk.Tk()
        root.withdraw()
        try:
            sender_text = tk.Text(root)
            sender_text.insert("1.0", "张三 13800138000 北京")

            frame = AppFrame.__new__(AppFrame)
            frame._sender_text = sender_text
            frame.clipboard_get = mock.Mock(return_value="李四\n13900139000")

            frame._on_sender_paste()

            self.assertEqual(
                sender_text.get("1.0", "end-1c"),
                "李四 13900139000",
            )
        finally:
            root.destroy()

    def test_sender_text_height_is_half_receiver_text_height(self):
        """回归：寄件文本框高度应为 3 行，收件文本框仍保持 6 行。"""
        root = tk.Tk()
        root.withdraw()
        try:
            parent = tk.Frame(root)
            frame = AppFrame.__new__(AppFrame)

            frame._build_sender_card(parent)
            frame._build_receiver_card(parent)

            self.assertEqual(int(frame._sender_text.cget("height")), 3)
            self.assertEqual(int(frame._receiver_text.cget("height")), 6)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
