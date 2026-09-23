"""excel_exporter 单行与双行表头导出单元测试。"""
import os
import tempfile
import unittest

import openpyxl

from excel_exporter import write_export_excel


class ExcelExporterTest(unittest.TestCase):
    """覆盖单双行表头布局、配色、冻结窗格和下拉验证范围。"""

    def test_double_row_header_and_data(self):
        categories = [
            ("绑定单号", ["商家订单号", "平台订单号"]),
            ("收件人信息", ["收件人姓名"]),
        ]
        rows = [
            ["A1", "B1", "张三"],
            ["A2", "B2", "李四"],
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            dropdown = {"收件人姓名": ["张三", "李四"]}
            write_export_excel(path, categories, rows, dropdown)
            wb = openpyxl.load_workbook(path)
            ws = wb.active

            self.assertEqual(ws.cell(1, 1).value, "绑定单号")
            self.assertEqual(ws.cell(1, 3).value, "收件人信息")
            self.assertEqual(ws.cell(2, 1).value, "商家订单号")
            self.assertEqual(ws.cell(2, 2).value, "平台订单号")
            self.assertEqual(ws.cell(2, 3).value, "收件人姓名")
            self.assertEqual(ws.cell(3, 1).value, "A1")
            self.assertEqual(ws.cell(3, 2).value, "B1")
            self.assertEqual(ws.cell(4, 3).value, "李四")
            self.assertEqual(ws.freeze_panes, "A3")
            self.assertGreaterEqual(len(ws.merged_cells.ranges), 1)
            ranges = [str(dv.sqref) for dv in ws.data_validations.dataValidation]
            self.assertIn("C3:C1002", ranges)
            wb.close()

    def test_single_row_header_and_data(self):
        categories = [
            {
                "name": "绑定单号",
                "color": "D9E1F2",
                "fields": ["商家订单号", "平台订单号"],
            },
            {
                "name": "收件人信息",
                "color": "E2EFDA",
                "fields": ["收件人姓名"],
            },
        ]
        rows = [["A1", "B1", "张三"]]
        dropdown = {"收件人姓名": ["张三", "李四"]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            write_export_excel(
                path,
                categories,
                rows,
                dropdown,
                single_row_header=True,
            )
            wb = openpyxl.load_workbook(path)
            ws = wb.active

            self.assertEqual(ws.cell(1, 1).value, "商家订单号")
            self.assertEqual(ws.cell(1, 2).value, "平台订单号")
            self.assertEqual(ws.cell(1, 3).value, "收件人姓名")
            self.assertEqual(ws.cell(2, 1).value, "A1")
            self.assertEqual(ws.cell(2, 2).value, "B1")
            self.assertEqual(ws.cell(2, 3).value, "张三")
            self.assertEqual(ws.freeze_panes, "A2")
            self.assertEqual(len(ws.merged_cells.ranges), 0)
            self.assertTrue(
                str(ws.cell(1, 1).fill.fgColor.rgb).endswith("D9E1F2")
            )
            self.assertTrue(
                str(ws.cell(1, 3).fill.fgColor.rgb).endswith("E2EFDA")
            )
            ranges = [str(dv.sqref) for dv in ws.data_validations.dataValidation]
            self.assertIn("C2:C1001", ranges)
            wb.close()


if __name__ == "__main__":
    unittest.main()
