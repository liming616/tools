"""文本识别中物品信息并入面单备注、不进入物品类型的单元测试。"""
import unittest
from types import SimpleNamespace
from unittest import mock

import main as main_mod
from main import App
from template_manager import empty_fields_dict


def make_app(profiles=None):
    """构造仅含转储逻辑所需属性的 App 实例。"""
    app = App.__new__(App)
    app._prefill_profiles = list(profiles or [])
    app._collect_table = mock.Mock()
    app._row_data = []
    app._visible_fields = ["name", "phone", "items_text", "notes"]
    app._capture_count = 0
    app._dirty = False
    app._update_count_display = mock.Mock()
    return app


def _parsed_addr():
    """返回最小可用的地址解析结果桩。"""
    return SimpleNamespace(
        province="", city="", district="", development_zone="", township="",
        road="", community="", landmark="", building="", unit="", room="",
        full_detail="", full_address="",
    )


class TransferItemsToNotesTest(unittest.TestCase):
    """覆盖：物品原文并入面单备注，物品类型不再由识别结果填充。"""

    def _transfer(self, app, order):
        with mock.patch.object(main_mod, "parse_order", return_value=order), \
                mock.patch.object(main_mod, "parse_address_safe",
                                  return_value=_parsed_addr()), \
                mock.patch.object(main_mod, "empty_fields_dict",
                                  side_effect=lambda: empty_fields_dict()), \
                mock.patch.object(main_mod, "build_row_tuple",
                                  return_value=("", "", "", "")), \
                mock.patch.object(main_mod, "score_fields",
                                  return_value=(0.9, [], {"name": 1.0})), \
                mock.patch.object(main_mod, "is_low_confidence",
                                  return_value=False):
            return app._transfer_line("测试文本")

    def test_items_merged_into_notes_not_items_type(self):
        app = make_app()
        order = SimpleNamespace(
            name="收件人", phone="13700137000", landline="", address="北京市朝阳区",
            items=[{"name": "大桃", "qty": 2, "raw": "大桃 2箱"}],
            notes="周末配送",
        )
        ok, warnings_list, overall = self._transfer(app, order)
        self.assertTrue(ok)
        fields = app._row_data[0]["fields"]
        self.assertEqual(fields["items"], [])
        self.assertEqual(fields["items_text"], "")
        self.assertIn("大桃 2箱", fields["notes"])
        self.assertIn("周末配送", fields["notes"])

    def test_notes_only_when_no_items(self):
        app = make_app()
        order = SimpleNamespace(
            name="收件人", phone="13700137000", landline="", address="北京市朝阳区",
            items=[], notes="周末配送",
        )
        ok, _, _ = self._transfer(app, order)
        self.assertTrue(ok)
        fields = app._row_data[0]["fields"]
        self.assertEqual(fields["items"], [])
        self.assertEqual(fields["notes"], "周末配送")

    def test_prefill_items_type_still_filled(self):
        app = make_app([{
            "enabled": True,
            "label": "",
            "values": {"物品类型": "生鲜", "时效产品": "次日达"},
        }])
        order = SimpleNamespace(
            name="收件人", phone="13700137000", landline="", address="北京市朝阳区",
            items=[{"name": "大桃", "qty": 2, "raw": "大桃 2箱"}],
            notes="",
        )
        ok, _, _ = self._transfer(app, order)
        self.assertTrue(ok)
        fields = app._row_data[0]["fields"]
        self.assertEqual(fields["items"], [])
        self.assertEqual(fields["items_text"], "生鲜")
        self.assertIn("大桃 2箱", fields["notes"])


if __name__ == "__main__":
    unittest.main()
