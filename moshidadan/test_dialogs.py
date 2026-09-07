"""寄件信息配置弹窗字段收集测试（不触发弹窗）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dialogs import SenderConfigDialog


class _FakeVar:
    """模拟 tk.StringVar：仅提供 get()，避免依赖真实 Tk 根实例。"""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class DialogContextTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
