"""数据持久化单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json

from data_store import (
    save_collected, load_collected, clear_collected,
    save_collected_by_template, load_collected_by_template,
    clear_collected_by_template,
    _data_file,
)


class DataStoreTest(unittest.TestCase):
    def tearDown(self):
        clear_collected()

    def test_save_and_load(self):
        rows = [{"fields": {"name": "张三"}, "raw": "raw text"}]
        self.assertTrue(save_collected(rows))
        loaded = load_collected()
        self.assertEqual(loaded[0]["fields"]["name"], "张三")

    def test_clear(self):
        save_collected([{"fields": {"name": "x"}, "raw": ""}])
        self.assertTrue(clear_collected())
        self.assertEqual(load_collected(), [])

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_collected(), [])

    def test_template_save_load_isolated(self):
        save_collected_by_template("JD_MONTHLY", [{"fields": {"name": "张三"}}])
        save_collected_by_template("JD_OFFICIAL", [{"fields": {"name": "李四"}}])
        self.assertEqual(len(load_collected_by_template("JD_MONTHLY")), 1)
        self.assertEqual(len(load_collected_by_template("JD_OFFICIAL")), 1)

    def test_template_clear_only_target(self):
        save_collected_by_template("JD_MONTHLY", [{"fields": {"name": "张三"}}])
        save_collected_by_template("JD_OFFICIAL", [{"fields": {"name": "李四"}}])
        self.assertTrue(clear_collected_by_template("JD_MONTHLY"))
        self.assertEqual(load_collected_by_template("JD_MONTHLY"), [])
        self.assertNotEqual(load_collected_by_template("JD_OFFICIAL"), [])

    def test_template_missing_returns_empty(self):
        self.assertEqual(load_collected_by_template("SF"), [])

    def test_legacy_items_migrated_to_template(self):
        path = _data_file()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"items": [{"fields": {"name": "旧数据"}}]}, f, ensure_ascii=False)
        rows = load_collected_by_template("JD_MONTHLY")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fields"]["name"], "旧数据")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("items_by_template", data)


if __name__ == "__main__":
    unittest.main()
