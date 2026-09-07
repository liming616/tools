"""template_manager v2.0.1 扩展测试：列表表头 + 导出分类映射。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from template_manager import get_list_headers, get_export_categories, flatten_export_fields


DEFAULT_CATEGORIES = [
    {"name": "必填项", "color": "FFF2CC", "required": True, "fields": ["收货人", "联系方式"]},
    {"name": "其他", "color": "DDEBF7", "fields": ["件数", "运单备注"]},
]


class TemplateManagerV201Test(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "template_configs": {
                "JD_MONTHLY": {"list_headers": ["序号", "商家订单号"], "export_categories": DEFAULT_CATEGORIES},
                "JD_OFFICIAL": {"list_headers": ["序号", "收货人"], "export_categories": DEFAULT_CATEGORIES},
            }
        }

    def test_get_list_headers(self):
        self.assertEqual(get_list_headers("JD_MONTHLY", self.cfg), ["序号", "商家订单号"])

    def test_get_export_categories(self):
        cats = get_export_categories("JD_OFFICIAL", self.cfg)
        self.assertTrue(cats[0].get("required"))

    def test_flatten_export_fields(self):
        fields = flatten_export_fields(DEFAULT_CATEGORIES)
        self.assertEqual(fields, ["收货人", "联系方式", "件数", "运单备注"])

    def test_missing_key_empty(self):
        self.assertEqual(get_list_headers("SF", self.cfg), [])
        self.assertEqual(get_export_categories("SF", self.cfg), [])


if __name__ == "__main__":
    unittest.main()
