"""app_config 加载逻辑单元测试。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config_manager


class LoadAppConfigTest(unittest.TestCase):
    """覆盖: 正常读取 / 文件缺失 / JSON 损坏 / 空值回退默认值。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _config_path(self):
        return os.path.join(self.tmp.name, config_manager.APP_CONFIG_FILE)

    def _write(self, content):
        with open(self._config_path(), "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)

    def test_load_valid_config(self):
        self._write({"app_name": "产地快打", "version": "v1.0.3"})
        with patch("config_manager.resource_path", return_value=self._config_path()):
            config = config_manager.load_app_config()
        self.assertEqual(config["app_name"], "产地快打")
        self.assertEqual(config["version"], "v1.0.3")

    def test_missing_file_returns_default(self):
        with patch("config_manager.resource_path", return_value=self._config_path()):
            config = config_manager.load_app_config()
        self.assertEqual(config, config_manager.DEFAULT_APP_CONFIG)

    def test_corrupted_file_returns_default(self):
        with open(self._config_path(), "w", encoding="utf-8") as f:
            f.write("{not-json")
        with patch("config_manager.resource_path", return_value=self._config_path()):
            config = config_manager.load_app_config()
        self.assertEqual(config["version"], "v1.0.3")

    def test_blank_values_use_default(self):
        self._write({"app_name": "  ", "version": ""})
        with patch("config_manager.resource_path", return_value=self._config_path()):
            config = config_manager.load_app_config()
        self.assertEqual(config, config_manager.DEFAULT_APP_CONFIG)

    def test_nested_template_config_loaded(self):
        self._write({
            "app_name": "产地快打",
            "version": "v1.0.3",
            "templates": {
                "default": "JD",
                "options": [
                    {"key": "JD", "label": "JD下单模板", "enabled": True},
                    {"key": "SF", "label": "SF下单模板", "enabled": False},
                ],
            },
            "template_configs": {
                "JD": {
                    "header_style": "double_row",
                    "categories": [{"name": "绑定单号", "fields": ["商家订单号"]}],
                }
            },
        })
        with patch("config_manager.resource_path", return_value=self._config_path()):
            config = config_manager.load_app_config()
        self.assertEqual(config["templates"]["default"], "JD")
        self.assertFalse(config["templates"]["options"][1]["enabled"])
        self.assertEqual(
            config["template_configs"]["JD"]["categories"][0]["fields"],
            ["商家订单号"],
        )


if __name__ == "__main__":
    unittest.main()
