"""编辑预制信息按钮可用性单元测试。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as main_mod
from main import App


class FakeButton:
    def __init__(self):
        self.state = None

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class FakeVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


def make_app(profiles):
    app = App.__new__(App)
    app._prefill_var = FakeVar()
    app._edit_prefill_btn = FakeButton()
    app._prefill_echo = None
    app._prefill_echo_frame = None
    app._template_headers = ["寄件人姓名", "寄件人手机", "寄件人地址", "时效产品"]
    app._prefill_profiles = list(profiles)
    app.config = {"prefill_profiles": list(profiles)}
    app._flash_status = mock.Mock()
    return app


class PrefillButtonTest(unittest.TestCase):
    def test_button_enabled_without_profiles(self):
        app = make_app([])
        app._update_prefill_status()
        self.assertEqual(app._edit_prefill_btn.state, "normal")

    def test_button_enabled_with_profiles(self):
        app = make_app([{"enabled": True, "label": "档案1", "values": {}}])
        app._update_prefill_status()
        self.assertEqual(app._edit_prefill_btn.state, "normal")

    def test_edit_prefill_creates_blank_profile_when_empty(self):
        app = make_app([])
        confirmed = [{"enabled": True, "label": "", "values": {"寄件人姓名": "张三"}}]
        with mock.patch.object(App, "_open_prefill_dialog", return_value=confirmed) as dlg, \
                mock.patch.object(main_mod, "save_config") as save:
            app._edit_prefill()
        self.assertEqual(dlg.call_count, 1)
        headers, profiles = dlg.call_args[0]
        self.assertEqual(headers, main_mod.PREFILL_FIELDS)
        self.assertEqual(len(profiles), 1)
        self.assertTrue(profiles[0]["enabled"])
        self.assertEqual(profiles[0]["label"], "")
        self.assertEqual(app._prefill_profiles[0]["values"]["寄件人姓名"], "张三")
        save.assert_called_once_with(app.config)

    def test_edit_prefill_keeps_existing_profiles(self):
        existing = [{"enabled": False, "label": "旧档案", "values": {"寄件人姓名": "李四"}}]
        app = make_app(existing)
        with mock.patch.object(App, "_open_prefill_dialog", return_value=existing) as dlg, \
                mock.patch.object(main_mod, "save_config"):
            app._edit_prefill()
        headers, profiles = dlg.call_args[0]
        self.assertEqual(headers, main_mod.PREFILL_FIELDS)
        self.assertEqual(profiles, existing)
        self.assertEqual(app._prefill_profiles, existing)

    def test_validate_prefill_requires_other_fields_and_phone(self):
        missing = App._validate_prefill({})
        self.assertIn("寄件人姓名 为必填项", missing)
        self.assertIn("寄件人地址 为必填项", missing)
        self.assertIn("物品类型 为必填项", missing)
        self.assertIn("时效产品 为必填项", missing)
        self.assertIn("寄件人手机、寄件人座机至少填写一项", missing)

    def test_validate_prefill_accepts_all_fields(self):
        values = {
            "寄件人姓名": "张三",
            "寄件人手机": "13800000000",
            "寄件人座机": "010-88888888",
            "寄件人地址": "北京市朝阳区",
            "物品类型": "生鲜",
            "时效产品": "标准快递",
        }
        self.assertEqual(App._validate_prefill(values), [])

    def test_validate_prefill_accepts_phone_only(self):
        values = {
            "寄件人姓名": "张三",
            "寄件人手机": "13800000000",
            "寄件人座机": "",
            "寄件人地址": "北京市朝阳区",
            "物品类型": "生鲜",
            "时效产品": "标准快递",
        }
        self.assertEqual(App._validate_prefill(values), [])

    def test_validate_prefill_accepts_landline_only(self):
        values = {
            "寄件人姓名": "张三",
            "寄件人手机": "",
            "寄件人座机": "010-88888888",
            "寄件人地址": "北京市朝阳区",
            "物品类型": "生鲜",
            "时效产品": "标准快递",
        }
        self.assertEqual(App._validate_prefill(values), [])

    def test_validate_prefill_rejects_missing_both_phones(self):
        values = {
            "寄件人姓名": "张三",
            "寄件人手机": "",
            "寄件人座机": "",
            "寄件人地址": "北京市朝阳区",
            "物品类型": "生鲜",
            "时效产品": "标准快递",
        }
        self.assertIn(
            "寄件人手机、寄件人座机至少填写一项",
            App._validate_prefill(values),
        )

    def test_single_prefill_values_merges_profiles_later_wins(self):
        profiles = [
            {"enabled": True, "label": "档案1", "values": {"寄件人姓名": "张三", "寄件人手机": "1"}},
            {"enabled": False, "label": "档案2", "values": {"寄件人姓名": "李四", "寄件人地址": "北京"}},
        ]
        self.assertEqual(
            App._single_prefill_values(profiles),
            {"寄件人姓名": "李四", "寄件人手机": "1", "寄件人地址": "北京"},
        )

    def test_single_prefill_values_empty_when_no_profiles(self):
        self.assertEqual(App._single_prefill_values([]), {})


if __name__ == "__main__":
    unittest.main()