"""流向产品匹配算法单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_product import resolve_product


STRATEGY = {
    "rules": [
        {"provinces": ["北京", "天津", "河北"], "cities": [], "product": "生鲜标快"},
        {"provinces": [], "cities": ["苏州"], "product": "生鲜特快"},
    ],
    "fallback_product": "电商特惠",
}


class FlowProductTest(unittest.TestCase):
    def test_province_match(self):
        self.assertEqual(resolve_product(STRATEGY, "北京", "北京"), "生鲜标快")

    def test_city_match_precedence(self):
        self.assertEqual(resolve_product(STRATEGY, "江苏", "苏州"), "生鲜特快")

    def test_fallback(self):
        self.assertEqual(resolve_product(STRATEGY, "广东", "广州"), "电商特惠")

    def test_empty_province_city(self):
        self.assertEqual(resolve_product(STRATEGY, "", ""), "电商特惠")

    def test_no_rules_fallback(self):
        self.assertEqual(resolve_product({"rules": [], "fallback_product": "x"}, "北京", ""), "x")


if __name__ == "__main__":
    unittest.main()
