"""文本识别壳层单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recognition import normalize_text, recognize_line, recognize_batch


class RecognitionTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(
            normalize_text("张三\n13800138000\n北京市朝阳区xx路"),
            "张三 13800138000 北京市朝阳区xx路",
        )

    def test_recognize_line_fields(self):
        fields = recognize_line("收货人：李四 电话：13900139000 地址：上海市浦东新区博云路2号")
        self.assertEqual(fields["name"], "李四")
        self.assertEqual(fields["phone"], "13900139000")
        self.assertIn("上海市", fields["full_address"])
        self.assertEqual(fields["province"], "上海")

    def test_recognize_line_unknown_to_notes(self):
        fields = recognize_line("这是一条无法识别的备注内容")
        self.assertTrue(fields["notes"])

    def test_recognize_batch_multiline(self):
        rows = recognize_batch("张三 13800138000 北京市朝阳区xx路\n李四 13900139000 上海市浦东新区博云路2号")
        self.assertEqual(len(rows), 2)

    def test_notes_clean_without_address_junk(self):
        fields = recognize_line("张三 13800138000 北京市朝阳区xx路1号 苹果x2 周末配送")
        self.assertNotIn("13800138000", fields["notes"])
        self.assertNotIn("朝阳区xx路", fields["notes"])
        self.assertIn("周末配送", fields["notes"])

    def test_notes_prefer_explicit_tag(self):
        fields = recognize_line("地址：北京市朝阳区xx路1号\n备注：冷冻保存")
        self.assertIn("冷冻保存", fields["notes"])


if __name__ == "__main__":
    unittest.main()
