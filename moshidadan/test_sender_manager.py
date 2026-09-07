"""寄件人管理单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sender_manager import SenderManager


def make_config():
    return {
        "selected_sender": "寄件人1",
        "sender_profiles": [
            {"id": "1", "label": "寄件人1", "sender_name": "张伟", "sender_phone": "13800001111", "sender_landline": "", "sender_address": "北京市朝阳区", "items_text": "食品", "temperature_layer": "冷藏(0-4℃)", "payment_method": "寄付月结"},
            {"id": "2", "label": "寄件人2", "sender_name": "", "sender_phone": "", "sender_landline": "", "sender_address": "", "items_text": "", "temperature_layer": "", "payment_method": ""},
        ],
        "default_sender": {"sender_name": "默认公司", "sender_phone": "13900139000", "sender_landline": "", "sender_address": "上海市", "items_text": "文件", "temperature_layer": "冷藏(0-4℃)", "payment_method": "到付"},
        "selected_strategy": {"JD_MONTHLY": "p1", "JD_OFFICIAL": "q1"},
    }


class SenderManagerTest(unittest.TestCase):
    def test_selected_full(self):
        mgr = SenderManager(make_config())
        fields = mgr.get_selected_sender_fields()
        self.assertEqual(fields["sender_name"], "张伟")
        self.assertEqual(fields["sender_phone"], "13800001111")

    def test_empty_field_falls_to_default(self):
        cfg = make_config()
        cfg["selected_sender"] = "寄件人2"
        mgr = SenderManager(cfg)
        fields = mgr.get_selected_sender_fields()
        self.assertEqual(fields["sender_name"], "默认公司")
        self.assertEqual(fields["sender_address"], "上海市")

    def test_temperature(self):
        mgr = SenderManager(make_config())
        self.assertEqual(mgr.get_temperature_layer(), "冷藏(0-4℃)")

    def test_payment(self):
        mgr = SenderManager(make_config())
        self.assertEqual(mgr.get_payment_method("JD_MONTHLY"), "寄付月结")

    def test_strategy(self):
        mgr = SenderManager(make_config())
        self.assertEqual(mgr.get_selected_strategy_id("JD_MONTHLY"), "p1")
        mgr.set_selected_strategy("JD_MONTHLY", "p2")
        self.assertEqual(mgr.get_selected_strategy_id("JD_MONTHLY"), "p2")


if __name__ == "__main__":
    unittest.main()
