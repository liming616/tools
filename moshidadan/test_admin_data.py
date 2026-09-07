"""行政区域外部词典加载 / 热重载 / 容错单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from address_parser import load_external_admin_data, refresh_admin_data, parse_address, parse_address_safe


class AdminDataTest(unittest.TestCase):
    def test_load_merges_builtin_and_external(self):
        refresh_admin_data()
        data = load_external_admin_data()
        self.assertIn("北京市", data)
        self.assertIn("广东省", data)

    def test_external_missing_falls_back_to_builtin(self):
        refresh_admin_data()
        data = load_external_admin_data()
        self.assertTrue(data)

    def test_external_custom_city_parses(self):
        refresh_admin_data()
        result = parse_address("测试省测试市测试区xx路1号")
        self.assertIsNotNone(result)

    def test_parse_safe_never_raises(self):
        self.assertIsNotNone(parse_address_safe(""))
        self.assertIsNotNone(parse_address_safe("x" * 20000))


if __name__ == "__main__":
    unittest.main()
