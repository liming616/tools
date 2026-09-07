"""app_config.json v2.0.1 结构完整性测试。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import load_app_config, get_flow_strategies


class AppConfigV201Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_config.json")
        with open(path, "r", encoding="utf-8") as f:
            cls.cfg = json.load(f)

    def test_meta(self):
        self.assertEqual(self.cfg["app_name"], "产地快打")
        self.assertEqual(self.cfg["version"], "v2.0.1")
        self.assertEqual(self.cfg["sender_defaults"]["temperature_layer"], "冷藏(0-4℃)")

    def test_templates_options(self):
        opts = self.cfg["templates"]["options"]
        keys = [o["key"] for o in opts]
        self.assertEqual(keys, ["JD_MONTHLY", "JD_OFFICIAL", "SF"])
        self.assertFalse(next(o for o in opts if o["key"] == "SF")["enabled"])

    def test_list_headers(self):
        month = self.cfg["template_configs"]["JD_MONTHLY"]["list_headers"]
        self.assertEqual(len(month), 16)
        self.assertEqual(month[0], "序号")
        official = self.cfg["template_configs"]["JD_OFFICIAL"]["list_headers"]
        self.assertEqual(len(official), 9)
        self.assertEqual(official[0], "序号")

    def test_official_required_category(self):
        cats = self.cfg["template_configs"]["JD_OFFICIAL"]["export_categories"]
        required = [c for c in cats if c.get("required")]
        self.assertTrue(required)
        self.assertEqual(required[0]["color"], "FFF2CC")

    def test_flow_product(self):
        for key in ("JD_MONTHLY", "JD_OFFICIAL"):
            self.assertIn(key, self.cfg["flow_product_config"])
            strategies = self.cfg["flow_product_config"][key]["strategies"]
            self.assertTrue(strategies)
            for s in strategies:
                self.assertIn("rules", s)
                self.assertIn("fallback_product", s)

    def test_load_app_config_keeps_flow_product(self):
        """回归：load_app_config 不应再按白名单丢弃 flow_product_config/sender_defaults。"""
        app = load_app_config()
        self.assertIn("flow_product_config", app)
        self.assertIn("sender_defaults", app)
        self.assertEqual(app["flow_product_config"], self.cfg["flow_product_config"])
        self.assertNotEqual(get_flow_strategies(app, "JD_MONTHLY"), [])


if __name__ == "__main__":
    unittest.main()
