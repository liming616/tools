"""解析增强逻辑单元测试：地址标签切块、无省市区地址、商品精准提取、姓名打分。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from address_parser import parse_address_safe
from parser import parse_order, parse_items, _score_name_candidate
from recognition import recognize_line


class AddressTagTest(unittest.TestCase):
    def test_address_tag_not_swallow_product(self):
        order = parse_order("地址：北京市朝阳区xx路1号 商品：苹果 x2 备注：尽快")
        self.assertIn("北京市朝阳区xx路1号", order.address)
        self.assertNotIn("商品", order.address)
        self.assertNotIn("苹果", order.address)
        self.assertTrue(order.items)

    def test_address_tag_stops_at_newline(self):
        order = parse_order("地址：上海市浦东新区博云路2号\n备注：冷冻")
        self.assertEqual(order.address.strip(), "上海市浦东新区博云路2号")
        self.assertNotIn("备注", order.address)
        self.assertIn("冷冻", order.notes)


class NoProvinceAddressTest(unittest.TestCase):
    def test_address_without_province(self):
        order = parse_order("南山区科技园路1号科兴科学园B3栋501 王五 13800138000")
        self.assertTrue(order.address)
        self.assertIn("科技园路", order.address)

    def test_product_line_not_swallowed_as_address(self):
        order = parse_order("苹果5斤 香蕉3把")
        self.assertFalse(order.address and "苹果" in order.address)


class ItemExtractTest(unittest.TestCase):
    def test_strip_quantity(self):
        items = parse_items("苹果 x2；香蕉 3把")
        names = [it["name"] for it in items]
        self.assertIn("苹果", names)
        self.assertIn("香蕉", names)

    def test_strip_address_token(self):
        items = parse_items("衣服M码红色 科技园路1号")
        names = [it["name"] for it in items]
        self.assertTrue(any("衣服" in n for n in names))
        self.assertFalse(any("科技园路" in n for n in names))

    def test_strip_phone_token(self):
        items = parse_items("苹果 13800138000")
        names = [it["name"] for it in items]
        self.assertIn("苹果", names)
        self.assertFalse(any("138" in n for n in names))


class NameScoreTest(unittest.TestCase):
    def test_product_strong_negate(self):
        self.assertLess(_score_name_candidate("苹果"), 0.2)
        self.assertLess(_score_name_candidate("香蕉"), 0.2)

    def test_surname_name_high(self):
        self.assertGreater(_score_name_candidate("王芳"), 0.6)
        self.assertGreater(_score_name_candidate("李伟"), 0.6)

    def test_address_token_low(self):
        self.assertLess(_score_name_candidate("科技园"), 0.2)


class TextRecognitionNameTest(unittest.TestCase):
    def test_honorific_name_is_kept_and_not_moved_to_notes(self):
        """带称谓姓名应保留完整称谓，且不再进入备注。"""
        fields = recognize_line(
            "87025365 福建省福州市晋安区鼓山镇福马路420号"
            "福建省肿瘤医院科研楼3楼设备科 月饼 黄月英女士"
        )

        self.assertEqual(fields["name"], "黄月英女士")
        self.assertEqual(fields["items"], [])
        self.assertNotIn("黄月英女士", fields["notes"])
        self.assertIn("月饼", fields["notes"])


class CompoundDoorAddressTest(unittest.TestCase):
    def test_compound_door_number_is_preserved(self):
        """连字符门牌链不得拆分或重排。"""
        address = "浙江省杭州市临平区沁源公寓2-1-401"
        parsed = parse_address_safe(address)

        self.assertEqual(parsed.full_address, address)
        self.assertIn("2-1-401", parsed.full_address)

    def test_full_address_preserves_component_order(self):
        """完整地址应保留科研楼、楼层和科室的原始顺序。"""
        address = (
            "福建省福州市晋安区鼓山镇福马路420号"
            "福建省肿瘤医院科研楼3楼设备科"
        )
        parsed = parse_address_safe(address)

        self.assertEqual(parsed.full_address, address)


class AddressSymbolRecognitionTest(unittest.TestCase):
    def test_special_address_symbols_preserve_full_address(self):
        """常见地址特殊符号不得截断地址或进入备注。"""
        addresses = [
            "河北省廊坊市三河市燕郊镇中骏·四季花都1期7号楼203",
            "河北省廊坊市三河市燕郊镇中骏•四季花都1期7号楼203",
            "河北省廊坊市三河市燕郊镇中骏・四季花都1期7号楼203",
            "河北省廊坊市三河市燕郊镇中骏.四季花都1期7号楼203",
            "河北省廊坊市三河市燕郊镇中骏．四季花都1期7号楼203",
            "河北省廊坊市三河市燕郊镇某小区2#1#401",
            "河北省廊坊市三河市燕郊镇某小区2/1/401",
            "河北省廊坊市三河市燕郊镇某小区2-1-401",
            "河北省廊坊市三河市燕郊镇某小区2.1.401",
        ]

        for address in addresses:
            with self.subTest(address=address):
                fields = recognize_line(f"孙先生 18273823222 {address}")
                self.assertEqual(fields["full_address"], address)
                self.assertEqual(fields["notes"], "")
if __name__ == "__main__":
    unittest.main()
