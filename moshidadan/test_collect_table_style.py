"""Unit tests for collect table style configuration."""
import os
import sys
import unittest
import tkinter as tk
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as main_mod
from main import App


class CollectTableStyleTest(unittest.TestCase):
    """Cover collect table heading font, row/header height, and adaptive width."""

    def _make_app(self):
        app = App.__new__(App)
        app._collect_tree_container = mock.Mock()
        app._collect_tree_container.winfo_children.return_value = []
        return app

    def test_setup_collect_table_style(self):
        app = self._make_app()
        style = mock.Mock()
        tree = mock.Mock()
        header_font = mock.Mock()
        header_font.measure.return_value = 200

        with mock.patch.object(main_mod.ttk, "Style", return_value=style), \
                mock.patch.object(main_mod.ttk, "Treeview", return_value=tree), \
                mock.patch.object(main_mod.ttk, "Scrollbar", return_value=mock.Mock()), \
                mock.patch.object(main_mod.tkfont, "Font", return_value=header_font):
            app._setup_collect_table(["自定义列"], ["自定义列"])

        style.configure.assert_any_call(
            "Treeview", font=("Microsoft YaHei", 14), rowheight=40
        )
        style.configure.assert_any_call(
            "Treeview.Heading",
            font=("Microsoft YaHei", 16),
            padding=(1, 11),
        )

    def test_setup_collect_table_adaptive_column_width(self):
        app = self._make_app()
        style = mock.Mock()
        tree = mock.Mock()
        header_font = mock.Mock()
        header_font.measure.return_value = 200

        with mock.patch.object(main_mod.ttk, "Style", return_value=style), \
                mock.patch.object(main_mod.ttk, "Treeview", return_value=tree), \
                mock.patch.object(main_mod.ttk, "Scrollbar", return_value=mock.Mock()), \
                mock.patch.object(main_mod.tkfont, "Font", return_value=header_font):
            app._setup_collect_table(["自定义列"], ["自定义列"])

        tree.column.assert_any_call(
            "col0",
            width=224,
            minwidth=40,
            anchor=tk.CENTER,
            stretch=True,
        )

    def test_choose_collect_table_height_boundaries(self):
        self.assertEqual(App._choose_collect_table_height(800), 6)
        self.assertEqual(App._choose_collect_table_height(799), 5)
        self.assertEqual(App._choose_collect_table_height(760), 5)
        self.assertEqual(App._choose_collect_table_height(720), 4)
        self.assertEqual(App._choose_collect_table_height(680), 3)
        self.assertEqual(App._choose_collect_table_height(679), 2)

    def test_fit_window_to_screen_keeps_bottom_visible(self):
        app = App.__new__(App)
        app._root = mock.Mock()
        app._root.winfo_reqheight.return_value = 732
        app._read_screen_work_area = mock.Mock(return_value=(2560, 1360))

        app._fit_window_to_screen()

        app._root.geometry.assert_any_call("960x1360")
        app._root.geometry.assert_called_with("960x760+800+300")
        app._root.minsize.assert_called_once_with(700, 480)


if __name__ == "__main__":
    unittest.main()
