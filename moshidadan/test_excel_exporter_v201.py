"""excel_exporter v2.0.1 扩展测试：dict 分类兼容 + 必填标黄。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openpyxl
from excel_exporter import write_export_excel, flatten_categories


class ExcelExporterV201Test(unittest.TestCase):
    def test_dict_category(self):
        path = os.path.join(tempfile.mkdtemp(), "out.xlsx")
        categories = [
            {"name": "必填项", "color": "FFF2CC", "required": True, "fields": ["收件人", "联系方式"]},
            {"name": "其他", "color": "DDEBF7", "fields": ["备注"]},
        ]
        rows = [["张三", "13800138000", "快递放门口"]]
        write_export_excel(path, categories, rows)
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        self.assertEqual(ws.cell(row=2, column=1).value, "收件人")
        self.assertEqual(ws.cell(row=3, column=1).value, "张三")
        self.assertEqual(ws.cell(row=1, column=1).value, "必填项（必填）")
        wb.close()

    def test_flatten_dict_categories(self):
        cats = [
            {"name": "A", "fields": ["x", "y"]},
            {"name": "B", "fields": ["z"]},
        ]
        self.assertEqual(flatten_categories(cats), ["x", "y", "z"])

    def test_official_product_dropdown_contains_only_two_flow_products(self):
        """京东散单时效产品下拉框应仅包含生鲜标快和生鲜特快。"""
        from config_manager import load_app_config

        cfg = load_app_config()
        options = cfg["template_configs"]["JD_OFFICIAL"]["dropdown_options"]["时效产品"]
        path = os.path.join(tempfile.mkdtemp(), "official.xlsx")
        categories = [{"name": "必填项", "fields": ["时效产品"]}]
        write_export_excel(path, categories, [["生鲜标快"]], {"时效产品": options})
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        self.assertEqual(len(ws.data_validations.dataValidation), 1)
        dd_sheet = wb["下拉选项"]
        exported_options = [
            dd_sheet.cell(row=row, column=1).value
            for row in range(2, 4)
        ]
        self.assertEqual(exported_options, options)


if __name__ == "__main__":
    unittest.main()
