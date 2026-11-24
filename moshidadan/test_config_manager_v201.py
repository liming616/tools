"""config_manager v2.0.1 扩展测试：温层默认值 + 流向策略读取。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import (
    DEFAULT_CONFIG,
    get_default_temperature,
    get_flow_strategies,
    validate_flow_strategy_selection,
)


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


    def test_flow_strategy_selection_validation(self):
        """存在策略时，空选择和失效选择都必须校验失败。"""
        strategies = [{"id": "p0"}, {"id": "p4"}]

        self.assertEqual(validate_flow_strategy_selection(strategies, "p4"), [])
        self.assertEqual(validate_flow_strategy_selection([], ""), [])
        self.assertEqual(
            validate_flow_strategy_selection(strategies, ""),
            ["流向产品配置 为必填项"],
        )
        self.assertEqual(
            validate_flow_strategy_selection(strategies, "invalid"),
            ["流向产品配置 为必填项"],
        )
    def test_auto_recognize_and_combo_copy_default_enabled(self):
        """自动识别和连击复制默认都应开启。"""
        self.assertTrue(DEFAULT_CONFIG["auto_recognize"])
        self.assertTrue(DEFAULT_CONFIG["combo_copy"])
if __name__ == "__main__":
    unittest.main()
