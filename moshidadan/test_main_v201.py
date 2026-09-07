"""主应用组装单元测试（用 __new__ 最小实例，不触发 Tk/剪贴板）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as main_mod


class MainV201Test(unittest.TestCase):
    def test_merge_fields_merges_sender_and_flow(self):
        app = main_mod.App.__new__(main_mod.App)
        app._app_config = {}
        app._config = {"selected_template": "JD_MONTHLY", "selected_strategy": {"JD_MONTHLY": "p1"}}
        app._template_key = "JD_MONTHLY"
        app._sender_mgr = mock.Mock()
        app._sender_mgr.get_selected_sender_fields.return_value = {
            "sender_name": "张伟", "sender_phone": "13800001111",
            "sender_landline": "", "sender_address": "北京", "sender_company": "", "sender_warehouse_code": "",
        }
        app._sender_mgr.get_temperature_layer.return_value = "冷藏(0-4℃)"
        app._sender_mgr.get_payment_method.return_value = "寄付月结"
        app._sender_mgr.get_selected_strategy_id.return_value = "p1"
        # 返回空 strategy 列表 -> delivery_product 保持为空
        with mock.patch.object(main_mod, "get_flow_strategies", return_value=[]):
            fields = app._merge_fields({
                "name": "李四", "phone": "13900139000", "full_address": "北京市朝阳区xx路",
                "province": "北京", "city": "北京", "delivery_product": "",
                "temperature_layer": "", "payment_method": "", "notes": "",
            })
        self.assertEqual(fields["sender_name"], "张伟")
        self.assertEqual(fields["temperature_layer"], "冷藏(0-4℃)")
        self.assertEqual(fields["payment_method"], "寄付月结")

    def test_export_excel_clears_and_saves(self):
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [{
            "fields": {
                "name": "张三", "full_address": "北京市朝阳区xx路", "phone": "13900139000",
            }
        }]
        app._template_key = "JD_MONTHLY"
        app._app_config = {
            "template_configs": {
                "JD_MONTHLY": {
                    "export_categories": [{"name": "收件人", "color": "FFF2CC", "fields": ["收件人姓名"]}],
                    "dropdown_options": None,
                }
            }
        }
        app._save_dir = ""
        with mock.patch.object(main_mod, "filedialog") as fd, \
                mock.patch.object(main_mod, "write_export_excel") as write, \
                mock.patch.object(main_mod, "messagebox") as msg:
            fd.asksaveasfilename.return_value = "out.xlsx"
            app._export_excel()
        write.assert_called_once()
        self.assertEqual(app._row_data, [])

    def _base_app(self):
        """构造最小 App 实例（不含导出所需额外字段）。"""
        app = main_mod.App.__new__(main_mod.App)
        app._template_key = "JD_MONTHLY"
        app._app_config = {
            "template_configs": {
                "JD_MONTHLY": {
                    "export_categories": [{"name": "收件人", "color": "FFF2CC", "fields": ["收件人姓名"]}],
                }
            }
        }
        return app

    def test_export_blocks_when_name_missing(self):
        app = self._base_app()
        app._row_data = [{"fields": {"full_address": "北京市", "phone": "13900139000"}}]
        with mock.patch.object(main_mod, "messagebox") as msg:
            app._export_excel()
        self.assertEqual(
            msg.showwarning.call_args[0][1], "第 1 条：收件人姓名必填"
        )

    def test_export_blocks_when_address_missing(self):
        app = self._base_app()
        app._row_data = [{"fields": {"name": "张三", "phone": "13900139000"}}]
        with mock.patch.object(main_mod, "messagebox") as msg:
            app._export_excel()
        self.assertEqual(
            msg.showwarning.call_args[0][1], "第 1 条：收件人地址必填"
        )

    def test_export_blocks_when_contact_missing(self):
        app = self._base_app()
        app._row_data = [{"fields": {"name": "张三", "full_address": "北京市"}}]
        with mock.patch.object(main_mod, "messagebox") as msg:
            app._export_excel()
        self.assertEqual(
            msg.showwarning.call_args[0][1], "第 1 条：收件人手机、座机至少填一项"
        )

    def test_template_switch_saves_old_and_loads_new(self):
        app = main_mod.App.__new__(main_mod.App)
        old_rows = [
            {"fields": {"name": "张三", "phone": "13800138000"}},
            {"fields": {"name": "李四", "phone": "13900139000"}},
        ]
        app._row_data = old_rows
        app._app_config = {}
        app._template_key = "JD_MONTHLY"
        app._config = {"selected_template": "JD_MONTHLY"}
        app._frame = mock.Mock()
        new_headers = ["序号", "收件人姓名", "收件人手机", "收件人地址"]
        with mock.patch.object(main_mod, "get_list_headers", return_value=new_headers), \
                mock.patch.object(main_mod, "save_config") as save, \
                mock.patch.object(main_mod, "save_collected_by_template") as save_tpl, \
                mock.patch.object(main_mod, "load_collected_by_template", return_value=[]) as load_tpl:
            app._on_template_changed("JD_OFFICIAL")
        # 旧模板数据落盘到对应分组
        save_tpl.assert_called_once_with("JD_MONTHLY", old_rows)
        # 新模板无历史 -> 列表清空，状态 0 条
        load_tpl.assert_called_once_with("JD_OFFICIAL")
        self.assertEqual(app._row_data, [])
        self.assertEqual(app._template_key, "JD_OFFICIAL")
        self.assertEqual(app._frame._list_headers, new_headers)
        self.assertEqual(app._config["selected_template"], "JD_OFFICIAL")
        app._frame.clear_rows.assert_called_once()
        app._frame.set_status.assert_called_once_with("已识别 0 条")
        save.assert_called_once()

    def test_template_switch_back_restores_data(self):
        app = main_mod.App.__new__(main_mod.App)
        saved_rows = [
            {"fields": {"name": "张三", "phone": "13800138000"}},
        ]
        app._row_data = []
        app._app_config = {}
        app._template_key = "JD_OFFICIAL"
        app._config = {"selected_template": "JD_OFFICIAL"}
        app._frame = mock.Mock()
        new_headers = ["序号", "收件人姓名", "收件人手机", "收件人地址"]
        with mock.patch.object(main_mod, "get_list_headers", return_value=new_headers), \
                mock.patch.object(main_mod, "save_config"), \
                mock.patch.object(main_mod, "save_collected_by_template"), \
                mock.patch.object(main_mod, "load_collected_by_template", return_value=saved_rows) as load_tpl:
            app._on_template_changed("JD_MONTHLY")
        # 切回原模板回显历史数据，状态 1 条
        load_tpl.assert_called_once_with("JD_MONTHLY")
        self.assertEqual(app._row_data, saved_rows)
        self.assertEqual(app._frame.set_status.call_args[0][0], "已识别 1 条")


if __name__ == "__main__":
    unittest.main()
