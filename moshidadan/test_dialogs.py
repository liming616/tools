"""寄件信息配置弹窗字段收集测试（不触发弹窗）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config_manager
from unittest import mock

import dialogs as dialogs_mod
from dialogs import SenderConfigDialog


class _FakeVar:
    """模拟 tk.StringVar：仅提供 get()，避免依赖真实 Tk 根实例。"""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class DialogContextTest(unittest.TestCase):
    def test_validate_sender_default_fields_reports_all_missing(self):
        """共享校验应完整返回所有默认寄件配置缺失项。"""
        validator = getattr(config_manager, "validate_sender_default_fields", None)
        self.assertTrue(callable(validator))

        fields = {
            "sender_name": "",
            "sender_phone": "",
            "sender_landline": "",
            "sender_address": "",
            "items_text": "",
        }

        errors = validator(fields)

        self.assertEqual(
            errors,
            [
                "寄件人姓名 为必填项",
                "寄件人地址 为必填项",
                "物品类型 为必填项",
                "寄件人手机、寄件人座机至少填写一项",
            ],
        )

    def test_collect_default_fields(self):
        dialog = SenderConfigDialog.__new__(SenderConfigDialog)
        dialog._default_vars = {
            "寄件人姓名": _FakeVar("默认公司"),
            "寄件人手机": _FakeVar("13900139000"),
            "寄件人座机": _FakeVar(""),
            "寄件人地址": _FakeVar("上海市"),
            "物品类型": _FakeVar("文件"),
            "温层": _FakeVar("冷藏(0-4℃)"),
        }
        fields = dialog.collect_default_fields()
        self.assertEqual(fields["sender_name"], "默认公司")
        self.assertEqual(fields["temperature_layer"], "冷藏(0-4℃)")

    def test_validate_default_fields_requires_required_fields(self):
        dialog = SenderConfigDialog.__new__(SenderConfigDialog)
        fields = {
            "sender_name": "", "sender_phone": "", "sender_landline": "",
            "sender_address": "", "items_text": "", "temperature_layer": "",
        }
        errors = dialog.validate_default_fields(fields)
        self.assertIn("寄件人姓名 为必填项", errors)
        self.assertIn("寄件人地址 为必填项", errors)
        self.assertIn("物品类型 为必填项", errors)
        self.assertIn("寄件人手机、寄件人座机至少填写一项", errors)

    def test_validate_default_fields_requires_phone_or_landline(self):
        dialog = SenderConfigDialog.__new__(SenderConfigDialog)
        fields = {
            "sender_name": "张三", "sender_phone": "", "sender_landline": "",
            "sender_address": "上海市", "items_text": "文件", "temperature_layer": "",
        }
        errors = dialog.validate_default_fields(fields)
        self.assertEqual(errors, ["寄件人手机、寄件人座机至少填写一项"])

    def test_validate_default_fields_accepts_phone_only(self):
        dialog = SenderConfigDialog.__new__(SenderConfigDialog)
        fields = {
            "sender_name": "张三", "sender_phone": "13900139000", "sender_landline": "",
            "sender_address": "上海市", "items_text": "文件", "temperature_layer": "",
        }
        self.assertEqual(dialog.validate_default_fields(fields), [])

    def test_validate_default_fields_accepts_landline_only(self):
        dialog = SenderConfigDialog.__new__(SenderConfigDialog)
        fields = {
            "sender_name": "张三", "sender_phone": "", "sender_landline": "010-88888888",
            "sender_address": "上海市", "items_text": "文件", "temperature_layer": "",
        }
        self.assertEqual(dialog.validate_default_fields(fields), [])

    def test_validate_default_fields_all_ok(self):
        dialog = SenderConfigDialog.__new__(SenderConfigDialog)
        fields = {
            "sender_name": "张三", "sender_phone": "13900139000",
            "sender_landline": "010-88888888", "sender_address": "上海市",
            "items_text": "文件", "temperature_layer": "冷藏(0-4℃)",
        }
        self.assertEqual(dialog.validate_default_fields(fields), [])

    def test_resolve_initial_temperature_uses_default_when_missing(self):
        self.assertEqual(
            SenderConfigDialog._resolve_initial_temperature({}, {}),
            "冷藏(0-4℃)",
        )

    def test_resolve_initial_temperature_keeps_explicit_empty(self):
        self.assertEqual(
            SenderConfigDialog._resolve_initial_temperature({"temperature_layer": ""}, {}),
            "",
        )

    def test_resolve_initial_temperature_uses_saved_value(self):
        self.assertEqual(
            SenderConfigDialog._resolve_initial_temperature(
                {"temperature_layer": "冷冻(≤-18℃)"}, {}
            ),
            "冷冻(≤-18℃)",
        )

    def test_initial_strategy_id_empty_without_saved_selection(self):
        """没有已保存策略时，不得自动选中第一条。"""
        strategies = [{"id": "p0", "name": "全流向-生鲜特快"}, {"id": "p4", "name": "全流向-生鲜标快"}]

        self.assertEqual(SenderConfigDialog._resolve_initial_strategy_id(strategies, ""), "")
        self.assertEqual(SenderConfigDialog._resolve_initial_strategy_id(strategies, "invalid"), "")
        self.assertEqual(SenderConfigDialog._resolve_initial_strategy_id(strategies, "p4"), "p4")

    def test_on_confirm_blocks_when_flow_strategy_not_selected(self):
        """流向策略未选择时不得保存配置。"""
        dialog = SenderConfigDialog.__new__(SenderConfigDialog)
        dialog._app_config = {
            "flow_product_config": {
                "JD_MONTHLY": {
                    "strategies": [
                        {"id": "p0", "name": "全流向-生鲜特快", "rules": [], "fallback_product": "生鲜特快"}
                    ]
                }
            }
        }
        dialog._template_key = "JD_MONTHLY"
        dialog._default_vars = {
            "寄件人姓名": _FakeVar("张三"),
            "寄件人手机": _FakeVar("13800138000"),
            "寄件人座机": _FakeVar(""),
            "寄件人地址": _FakeVar("北京市"),
            "物品类型": _FakeVar("文件"),
            "温层": _FakeVar(""),
        }
        dialog._strategy_var = _FakeVar("")
        dialog._config = {}
        dialog._on_save = mock.Mock()
        dialog.destroy = mock.Mock()

        with mock.patch.object(dialogs_mod.messagebox, "showwarning") as warning:
            dialog._on_confirm()

        warning.assert_called_once_with("校验未通过", "流向产品配置 为必填项")
        dialog._on_save.assert_not_called()
        dialog.destroy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
