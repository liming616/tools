"""config_manager v2.0.1 扩展测试：温层默认值 + 流向策略读取。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import get_default_temperature, get_flow_strategies


class ConfigManagerV201Test(unittest.TestCase):
    def setUp(self):
        self.app_config = {
            "sender_defaults": {"temperature_layer": "冷藏(0-4℃)"},
            "flow_product_config": {
                "JD_MONTHLY": {
                    "strategies": [{"id": "p1", "name": "s1", "rules": [], "fallback_product": "x"}]
                }
            },
        }

    def test_default_temperature(self):
        self.assertEqual(get_default_temperature(self.app_config), "冷藏(0-4℃)")

    def test_default_temperature_fallback(self):
        self.assertEqual(get_default_temperature({}), "冷藏(0-4℃)")

    def test_flow_strategies(self):
        strategies = get_flow_strategies(self.app_config, "JD_MONTHLY")
        self.assertEqual(len(strategies), 1)
        self.assertEqual(strategies[0]["id"], "p1")

    def test_flow_strategies_missing(self):
        self.assertEqual(get_flow_strategies(self.app_config, "JD_OFFICIAL"), [])


if __name__ == "__main__":
    unittest.main()
