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

    def test_merge_fields_fallback_first_strategy_when_no_selected(self):
        """回归：JD_OFFICIAL 未写入 selected_strategy 时，应回退到内置第一条流向策略。"""
        app = main_mod.App.__new__(main_mod.App)
        app._app_config = {}
        app._config = {"selected_template": "JD_OFFICIAL"}
        app._template_key = "JD_OFFICIAL"
        app._sender_mgr = mock.Mock()
        app._sender_mgr.get_selected_sender_fields.return_value = {}
        app._sender_mgr.get_temperature_layer.return_value = "冷藏(0-4℃)"
        app._sender_mgr.get_payment_method.return_value = ""
        # selected_strategy 为空 -> get_selected_strategy_id 返回空
        app._sender_mgr.get_selected_strategy_id.return_value = ""
        strategy_q1 = {
            "id": "q1", "name": "江浙沪-生鲜标快，其他-生鲜特快",
            "rules": [{"provinces": ["江苏", "浙江", "上海"], "cities": [], "product": "生鲜标快"}],
            "fallback_product": "生鲜特快",
        }
        with mock.patch.object(
            main_mod, "get_flow_strategies", return_value=[strategy_q1]
        ):
            fields = app._merge_fields({
                "name": "关羽", "full_address": "江苏省宿迁市宿城区", "delivery_product": "",
                "province": "江苏", "city": "宿迁", "temperature_layer": "",
                "payment_method": "", "notes": "",
            })
        # 未选中策略，但规则命中江苏省 -> 生鲜标快
        self.assertEqual(fields["delivery_product"], "生鲜标快")

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
        self.assertTrue(write.call_args.kwargs["single_row_header"])
        self.assertEqual(app._row_data, [])

    def test_export_excel_uses_double_header_for_official(self):
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [{
            "fields": {
                "name": "张三",
                "full_address": "北京市朝阳区xx路",
                "phone": "13900139000",
            }
        }]
        app._template_key = "JD_OFFICIAL"
        app._app_config = {
            "template_configs": {
                "JD_OFFICIAL": {
                    "export_categories": [
                        {
                            "name": "收件人",
                            "color": "FFF2CC",
                            "fields": ["收件人姓名"],
                        }
                    ],
                    "dropdown_options": None,
                }
            }
        }
        app._save_dir = ""
        with mock.patch.object(main_mod, "filedialog") as fd, \
                mock.patch.object(main_mod, "write_export_excel") as write, \
                mock.patch.object(main_mod, "messagebox"):
            fd.asksaveasfilename.return_value = "out.xlsx"
            app._export_excel()
        write.assert_called_once()
        self.assertFalse(write.call_args.kwargs["single_row_header"])

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

    def test_cell_edit_writes_back_to_correct_row(self):
        """回归：双击编辑「收件人姓名」单元格，值必须写回对应行、对应字段。"""
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [
            {"fields": {"name": "", "phone": ""}},
            {"fields": {"name": "", "phone": ""}},
        ]
        frame = mock.Mock()
        tree = mock.Mock()
        tree.index.return_value = 0  # item 在树中的 0-based 行序号
        tree.heading.side_effect = {
            "#1": "序号",
            "#2": "收件人姓名",
            "#3": "收件人手机",
        }.get
        frame._tree = tree
        app._frame = frame

        # col 实为列标识符 "#2"（不是表头文本），旧实现会解析失败导致编辑丢失
        app._on_cell_edited("iid1", "#2", "张三")

        self.assertEqual(app._row_data[0]["fields"]["name"], "张三")
        self.assertEqual(app._row_data[1]["fields"]["name"], "")
        self.assertEqual(app._row_data[0]["fields"]["phone"], "")

    def test_cell_edit_ignores_unmapped_column(self):
        """回归：编辑「序号」这类无字段映射的列，不应写入任何字段。"""
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [{"fields": {"name": ""}}]
        frame = mock.Mock()
        tree = mock.Mock()
        tree.index.return_value = 0
        tree.heading.side_effect = {"#1": "序号", "#2": "收件人姓名"}.get
        frame._tree = tree
        app._frame = frame

        app._on_cell_edited("iid1", "#1", "99")

        self.assertEqual(app._row_data[0]["fields"]["name"], "")

    def test_cell_edit_offical_header_maps_to_name(self):
        """回归：JD_OFFICIAL 表头「收货人」应映射到 name，保证编辑写回。"""
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [{"fields": {"name": ""}}]
        frame = mock.Mock()
        tree = mock.Mock()
        tree.index.return_value = 0
        tree.heading.side_effect = {"#1": "序号", "#2": "收货人"}.get
        frame._tree = tree
        app._frame = frame

        app._on_cell_edited("iid1", "#2", "王五")

        self.assertEqual(app._row_data[0]["fields"]["name"], "王五")

    def test_on_select_all_updates_rows(self):
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [
            {"fields": {"name": "a"}, "selected": False},
            {"fields": {"name": "b"}, "selected": False},
        ]
        app._on_select_all(True)
        self.assertTrue(all(r["selected"] for r in app._row_data))
        app._on_select_all(False)
        self.assertTrue(all(not r["selected"] for r in app._row_data))

    def test_delete_selected_rows_removes_checked(self):
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [
            {"fields": {"name": "a"}, "selected": True},
            {"fields": {"name": "b"}, "selected": False},
        ]
        app._template_key = "JD_MONTHLY"
        app._frame = mock.Mock()
        with mock.patch.object(main_mod, "messagebox") as msg, \
                mock.patch.object(main_mod, "save_collected_by_template") as save:
            msg.askyesno.return_value = True
            app._delete_selected_rows()
        self.assertEqual(len(app._row_data), 1)
        self.assertEqual(app._row_data[0]["fields"]["name"], "b")
        save.assert_called_once_with("JD_MONTHLY", app._row_data)

    def test_delete_selected_rows_prompts_when_none(self):
        app = main_mod.App.__new__(main_mod.App)
        app._row_data = [{"fields": {"name": "a"}, "selected": False}]
        with mock.patch.object(main_mod, "messagebox") as msg:
            app._delete_selected_rows()
        msg.showinfo.assert_called_once()
        self.assertEqual(len(app._row_data), 1)


    def test_auto_recognize_takes_priority_over_receiver_focus(self):
        """回归：自动识别开启时，收件框焦点不应拦截剪辑板文本。"""
        app = main_mod.App.__new__(main_mod.App)
        app._auto_recognize = True
        app._config = {}
        app._frame = mock.Mock()
        app._frame.get_sender_text.return_value = "张三 13800138000 北京 水果"
        app._frame.get_focus_target.return_value = "receiver"
        app._merge_fields = mock.Mock(return_value={"name": "李四"})
        app._append_row = mock.Mock()

        with mock.patch.object(
            main_mod, "recognize_batch", return_value=[{"name": "李四"}]
        ):
            app.handle_clipboard_text("李四 13900139000 上海 文件")

        app._frame.append_receiver.assert_not_called()
        app._append_row.assert_called_once_with({"name": "李四"})

    def test_auto_recognize_takes_priority_over_sender_focus(self):
        """回归：自动识别开启时，寄件框焦点也不应拦截剪辑板文本。"""
        app = main_mod.App.__new__(main_mod.App)
        app._auto_recognize = True
        app._config = {}
        app._frame = mock.Mock()
        app._frame.get_sender_text.return_value = "张三 13800138000 北京 水果"
        app._frame.get_focus_target.return_value = "sender"
        app._merge_fields = mock.Mock(return_value={"name": "李四"})
        app._append_row = mock.Mock()

        with mock.patch.object(
            main_mod, "recognize_batch", return_value=[{"name": "李四"}]
        ):
            app.handle_clipboard_text("李四 13900139000 上海 文件")

        app._frame.set_sender_text.assert_not_called()
        app._append_row.assert_called_once_with({"name": "李四"})

    def test_auto_recognize_blocks_when_sender_config_incomplete(self):
        """回归：寄件框为空且寄件信息配置不完整时，阻断识别并提示配置。"""
        app = main_mod.App.__new__(main_mod.App)
        app._auto_recognize = True
        app._config = {
            "default_sender": {
                "sender_name": "张三",
                "sender_address": "",
                "items_text": "",
                "sender_phone": "",
                "sender_landline": "",
            }
        }
        app._frame = mock.Mock()
        app._frame.get_sender_text.return_value = ""
        app._frame.get_focus_target.return_value = "receiver"
        app._append_row = mock.Mock()

        with mock.patch.object(main_mod, "messagebox") as msg:
            app.handle_clipboard_text("李四 13900139000 上海 文件")

        msg.showwarning.assert_called_once_with("提示", "请配置寄件信息")
        app._frame.append_receiver.assert_not_called()
        app._append_row.assert_not_called()

    def test_auto_recognize_continues_when_sender_config_complete(self):
        """回归：寄件框为空但寄件信息配置完整时，仍自动识别入列表。"""
        app = main_mod.App.__new__(main_mod.App)
        app._auto_recognize = True
        app._config = {
            "default_sender": {
                "sender_name": "张三",
                "sender_address": "北京",
                "items_text": "水果",
                "sender_phone": "13800138000",
                "sender_landline": "",
            }
        }
        app._frame = mock.Mock()
        app._frame.get_sender_text.return_value = ""
        app._frame.get_focus_target.return_value = "receiver"
        app._merge_fields = mock.Mock(return_value={"name": "李四"})
        app._append_row = mock.Mock()

        with mock.patch.object(
            main_mod, "recognize_batch", return_value=[{"name": "李四"}]
        ), mock.patch.object(main_mod, "messagebox") as msg:
            app.handle_clipboard_text("李四 13900139000 上海 文件")

        msg.showwarning.assert_not_called()
        app._frame.append_receiver.assert_not_called()
        app._append_row.assert_called_once_with({"name": "李四"})


    def _make_recognize_app(self, template_key="JD_MONTHLY"):
        """构造文本识别测试所需的 App 最小实例。"""
        app = main_mod.App.__new__(main_mod.App)
        app._template_key = template_key
        app._row_data = []
        app._config = {
            "selected_sender": "寄件人1",
            "default_sender": {
                "sender_name": "默认寄件人",
                "sender_phone": "13800138000",
                "sender_landline": "",
                "sender_address": "北京市朝阳区",
                "items_text": "水果",
            },
        }
        app._frame = mock.Mock()
        app._frame.get_receiver_text.return_value = "李四 13900139000 上海市浦东新区"
        app._frame.get_sender_text.return_value = ""
        app._append_row = mock.Mock()
        app._merge_fields = mock.Mock(return_value={"name": "李四"})
        return app

    def test_jd_monthly_text_recognize_prefers_sender_text(self):
        """京东月结：已选组且文本框有内容时，文本框解析结果优先。"""
        app = self._make_recognize_app()
        app._frame.get_sender_text.return_value = "王五 13700137000 北京市 文件"
        app._resolve_sender_fields = mock.Mock(
            return_value={"sender_name": "王五"}
        )
        app._default_sender_fields = mock.Mock()

        with mock.patch.object(
            main_mod, "recognize_batch", return_value=[{"name": "李四"}]
        ):
            app._on_recognize()

        app._resolve_sender_fields.assert_called_once_with(
            "王五 13700137000 北京市 文件"
        )
        app._default_sender_fields.assert_not_called()
        app._append_row.assert_called_once_with({"name": "李四"})
        app._frame.clear_receiver_text.assert_called_once()

    def test_jd_monthly_text_recognize_falls_back_default_when_sender_text_empty(self):
        """京东月结：已选组但文本框为空时，使用默认寄件配置。"""
        app = self._make_recognize_app()
        default_fields = {"sender_name": "默认寄件人"}
        app._resolve_sender_fields = mock.Mock()
        app._default_sender_fields = mock.Mock(return_value=default_fields)
        app._merge_fields.return_value = {"name": "李四", "sender_name": "默认寄件人"}

        with mock.patch.object(
            main_mod, "recognize_batch", return_value=[{"name": "李四"}]
        ):
            app._on_recognize()

        app._resolve_sender_fields.assert_not_called()
        app._default_sender_fields.assert_called_once()
        app._append_row.assert_called_once_with(
            {"name": "李四", "sender_name": "默认寄件人"}
        )

    def test_jd_monthly_text_recognize_blocks_when_default_incomplete(self):
        """京东月结：已选组但文本框为空且默认配置不完整时阻断。"""
        app = self._make_recognize_app()
        app._config["default_sender"]["items_text"] = ""

        with mock.patch.object(main_mod, "messagebox") as msg:
            app._on_recognize()

        msg.showwarning.assert_called_once_with("提示", "请配置寄件信息")
        app._append_row.assert_not_called()
        app._frame.clear_receiver_text.assert_not_called()

    def test_jd_monthly_text_recognize_ignores_text_when_no_sender_selected(self):
        """京东月结：未选择寄件人组时忽略文本框，使用默认寄件配置。"""
        app = self._make_recognize_app()
        app._config["selected_sender"] = ""
        app._frame.get_sender_text.return_value = "王五 13700137000 北京市 文件"
        app._resolve_sender_fields = mock.Mock()
        app._default_sender_fields = mock.Mock(
            return_value={"sender_name": "默认寄件人"}
        )

        with mock.patch.object(
            main_mod, "recognize_batch", return_value=[{"name": "李四"}]
        ):
            app._on_recognize()

        app._resolve_sender_fields.assert_not_called()
        app._default_sender_fields.assert_called_once()
        app._append_row.assert_called_once()

    def test_jd_monthly_text_recognize_blocks_when_no_group_and_default_incomplete(self):
        """京东月结：未选择寄件人组且默认配置不完整时阻断。"""
        app = self._make_recognize_app()
        app._config["selected_sender"] = ""
        app._config["default_sender"]["sender_name"] = ""

        with mock.patch.object(main_mod, "messagebox") as msg:
            app._on_recognize()

        msg.showwarning.assert_called_once_with("提示", "请配置寄件信息")
        app._append_row.assert_not_called()

    def test_non_jd_monthly_text_recognize_keeps_existing_behavior(self):
        """非京东月结模板保持原有寄件来源处理。"""
        app = self._make_recognize_app(template_key="JD_OFFICIAL")
        app._config["selected_sender"] = ""
        app._config["default_sender"]["items_text"] = ""
        app._resolve_sender_fields = mock.Mock(
            return_value={"sender_name": "旧逻辑寄件人"}
        )
        app._default_sender_fields = mock.Mock()

        with mock.patch.object(
            main_mod, "recognize_batch", return_value=[{"name": "李四"}]
        ):
            app._on_recognize()

        app._resolve_sender_fields.assert_called_once_with("")
        app._default_sender_fields.assert_not_called()
        app._append_row.assert_called_once()


if __name__ == "__main__":
    unittest.main()
