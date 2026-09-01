"""导出 Excel 全量字段逻辑单元测试。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as main_mod
from main import App


def make_app(selected_fields):
    """构造仅含导出逻辑所需属性的 App 实例。"""
    app = App.__new__(App)
    app._template_key = "JD"
    app.app_config = {
        "template_configs": {
            "JD": {
                "categories": [
                    {"name": "寄件人", "fields": ["寄件人姓名", "寄件人手机"]},
                    {"name": "收件人", "fields": ["收件人姓名", "收件人电话"]},
                ]
            }
        }
    }
    app._selected_export_fields = list(selected_fields)
    app._visible_headers = list(selected_fields)
    app._row_data = [{"fields": {"name": "张三", "phone": "13800138000"}}]
    app._prefill_profiles = [{
        "enabled": True,
        "label": "",
        "values": {
            "寄件人姓名": "张三",
            "寄件人手机": "13800138000",
            "寄件人地址": "上海市",
            "物品类型": "文件",
            "时效产品": "次日达",
        },
    }]
    app._flash_status = mock.Mock()
    app._collect_table = mock.Mock()
    app._collect_table.get_children.return_value = ["item1"]
    app._capture_count = 1
    app._update_count_display = mock.Mock()
    app._undo_btn = mock.Mock()
    return app


class ExportAllFieldsTest(unittest.TestCase):
    """覆盖：导出全量字段与「定义配置字段」勾选结果无关。"""

    def test_all_export_categories_ignores_selection(self):
        app = make_app(["收件人姓名"])
        categories = app._all_export_categories()
        self.assertEqual(
            categories,
            [
                ("寄件人", ["寄件人姓名", "寄件人手机"]),
                ("收件人", ["收件人姓名", "收件人电话"]),
            ],
        )

    def test_all_export_categories_empty_when_config_missing(self):
        app = App.__new__(App)
        app._template_key = "JD"
        app.app_config = {"template_configs": {"JD": {"categories": []}}}
        self.assertEqual(app._all_export_categories(), [])

    def test_export_excel_writes_all_config_fields(self):
        app = make_app(["收件人姓名"])
        with mock.patch.object(main_mod, "filedialog") as fd, \
                mock.patch.object(main_mod, "write_export_excel") as write:
            fd.asksaveasfilename.return_value = "out.xlsx"
            app._export_excel()
        write.assert_called_once()
        _, categories, rows = write.call_args[0]
        headers = [field for _, fields in categories for field in fields]
        self.assertEqual(
            headers, ["寄件人姓名", "寄件人手机", "收件人姓名", "收件人电话"]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "张三")

    def test_export_excel_clears_list_after_success(self):
        app = make_app(["收件人姓名"])
        with mock.patch.object(main_mod, "filedialog") as fd, \
                mock.patch.object(main_mod, "write_export_excel"):
            fd.asksaveasfilename.return_value = "out.xlsx"
            app._export_excel()
        self.assertEqual(app._row_data, [])
        self.assertEqual(app._capture_count, 0)
        self.assertEqual(len(app._undo_data), 1)
        app._collect_table.delete.assert_called_once_with("item1")
        app._undo_btn.configure.assert_called_once_with(state="normal")

    def test_merge_prefill_only_fills_non_visible_columns(self):
        app = make_app(["收件人姓名", "寄件人手机"])
        headers = ["寄件人姓名", "寄件人手机", "收件人姓名", "收件人电话"]
        rows = [["", "", "张三", "13800138000"]]
        merged = app._merge_prefill(rows, headers)
        # 可见列「寄件人手机」表格为空 → 导出为空，不被预制覆盖
        self.assertEqual(merged[0][1], "")
        # 未展示列「寄件人姓名」为空 → 用预制信息自动补值
        self.assertEqual(merged[0][0], "张三")

    def test_export_excel_blocks_when_prefill_empty(self):
        app = make_app(["收件人姓名"])
        app._prefill_profiles = []
        with mock.patch.object(main_mod, "messagebox") as msg, \
                mock.patch.object(main_mod, "write_export_excel") as write:
            app._export_excel()
        msg.showwarning.assert_called_once()
        write.assert_not_called()

    def test_export_excel_blocks_when_prefill_incomplete(self):
        app = make_app(["收件人姓名"])
        app._prefill_profiles = [{
            "enabled": True,
            "label": "",
            "values": {"寄件人姓名": "张三"},
        }]
        with mock.patch.object(main_mod, "messagebox") as msg, \
                mock.patch.object(main_mod, "write_export_excel") as write:
            app._export_excel()
        msg.showwarning.assert_called_once()
        write.assert_not_called()

    def test_export_excel_no_categories_shows_hint(self):
        app = App.__new__(App)
        app._template_key = "JD"
        app.app_config = {"template_configs": {"JD": {"categories": []}}}
        app._row_data = [{"fields": {"name": "张三"}}]
        app._prefill_profiles = []
        app._flash_status = mock.Mock()
        with mock.patch.object(main_mod, "messagebox") as msg, \
                mock.patch.object(main_mod, "write_export_excel") as write:
            app._export_excel()
        msg.showinfo.assert_called_once_with(
            "提示", "当前模板暂未配置可导出字段"
        )
        write.assert_not_called()
