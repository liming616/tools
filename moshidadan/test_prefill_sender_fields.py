"""预制信息填充到列表寄件人字段逻辑单元测试。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as main_mod
from main import App
from template_manager import empty_fields_dict


def make_app(profiles):
    """构造仅含转储/预制信息逻辑所需属性的 App 实例。"""
    app = App.__new__(App)
    app._prefill_profiles = list(profiles)
    app._collect_table = mock.Mock()
    app._row_data = []
    app._visible_fields = ["name", "phone"]
    app._capture_count = 0
    app._dirty = False
    app._update_count_display = mock.Mock()
    return app


def sample_profile(**overrides):
    """返回一份完整的启用预制档案，支持字段覆盖。"""
    values = {
        "寄件人姓名": "张三",
        "寄件人手机": "13800138000",
        "寄件人座机": "010-88888888",
        "寄件人地址": "上海市",
        "寄件人公司": "某某公司",
        "发货仓编码": "WH001",
    }
    values.update(overrides)
    return {"enabled": True, "label": "", "values": values}


class PrefillSenderFieldsTest(unittest.TestCase):
    """覆盖：剪贴板/文本识别转储到列表后，寄件人字段展示预制信息。"""

    def test_apply_prefill_fills_sender_fields(self):
        app = make_app([sample_profile()])
        fields = {
            "sender_name": "", "sender_phone": "", "sender_address": "",
            "sender_company": "", "sender_warehouse_code": "",
        }
        app._apply_prefill_sender_fields(fields)
        self.assertEqual(fields["sender_name"], "张三")
        self.assertEqual(fields["sender_phone"], "13800138000")
        self.assertEqual(fields["sender_address"], "上海市")
        self.assertEqual(fields["sender_company"], "某某公司")
        self.assertEqual(fields["sender_warehouse_code"], "WH001")

    def test_apply_prefill_phone_prefers_mobile(self):
        app = make_app([sample_profile()])
        fields = {"sender_phone": ""}
        app._apply_prefill_sender_fields(fields)
        self.assertEqual(fields["sender_phone"], "13800138000")

    def test_apply_prefill_phone_falls_back_to_landline(self):
        app = make_app([sample_profile(寄件人手机="")])
        fields = {"sender_phone": ""}
        app._apply_prefill_sender_fields(fields)
        self.assertEqual(fields["sender_phone"], "010-88888888")

    def test_apply_prefill_ignores_disabled_profiles(self):
        profile = sample_profile()
        profile["enabled"] = False
        app = make_app([profile])
        fields = {
            "sender_name": "", "sender_phone": "", "sender_address": "",
            "sender_company": "", "sender_warehouse_code": "",
        }
        app._apply_prefill_sender_fields(fields)
        self.assertEqual(fields["sender_name"], "")
        self.assertEqual(fields["sender_phone"], "")

    def test_apply_prefill_later_profile_wins(self):
        app = make_app([sample_profile(寄件人姓名="李四", 寄件人手机="13900139000")])
        app._prefill_profiles.append(
            {"enabled": True, "label": "", "values": {"寄件人姓名": "王五"}}
        )
        fields = {"sender_name": "", "sender_phone": ""}
        app._apply_prefill_sender_fields(fields)
        self.assertEqual(fields["sender_name"], "王五")
        self.assertEqual(fields["sender_phone"], "13900139000")

    def test_apply_prefill_keeps_existing_value(self):
        app = make_app([sample_profile()])
        fields = {"sender_name": "已有寄件人"}
        app._apply_prefill_sender_fields(fields)
        self.assertEqual(fields["sender_name"], "已有寄件人")

    def test_transfer_line_fills_sender_fields(self):
        app = make_app([sample_profile()])
        parsed_addr = SimpleNamespace(
            province="", city="", district="", development_zone="", township="",
            road="", community="", landmark="", building="", unit="", room="",
            full_detail="", full_address="",
        )
        order = SimpleNamespace(
            name="收件人", phone="13700137000", address="北京市朝阳区",
            items=[], notes="",
        )
        with mock.patch.object(main_mod, "parse_order", return_value=order), \
                mock.patch.object(main_mod, "parse_address_safe", return_value=parsed_addr), \
                mock.patch.object(main_mod, "empty_fields_dict",
                                  side_effect=lambda: empty_fields_dict()), \
                mock.patch.object(main_mod, "build_row_tuple",
                                  return_value=("", "")), \
                mock.patch.object(main_mod, "score_fields",
                                  return_value=(0.9, [], {"name": 1.0})), \
                mock.patch.object(main_mod, "is_low_confidence", return_value=False):
            ok, warnings_list, overall = app._transfer_line("测试文本")
        self.assertTrue(ok)
        self.assertEqual(warnings_list, [])
        self.assertEqual(overall, 0.9)
        self.assertEqual(app._row_data[0]["fields"]["sender_name"], "张三")
        self.assertEqual(app._row_data[0]["fields"]["sender_phone"], "13800138000")
        self.assertEqual(app._row_data[0]["fields"]["sender_address"], "上海市")
        self.assertEqual(app._row_data[0]["fields"]["sender_company"], "某某公司")
        self.assertEqual(app._row_data[0]["fields"]["sender_warehouse_code"], "WH001")


if __name__ == "__main__":
    unittest.main()
