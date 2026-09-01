"""
产地快打 — 生产级配置管理

特性:
  - JSON Schema 验证
  - 损坏配置文件自动修复
  - 配置版本迁移
  - 原子写入（先写临时文件再替换）
  - 默认值保护
"""

import json
import os
import shutil
from copy import deepcopy
from typing import Any, Optional

from paths import app_dir, resource_path

# ======================== 常量 ========================

CONFIG_FILE = os.path.join(app_dir(), "config.json")
CONFIG_VERSION = 2  # 当前配置版本

# 应用元数据配置（随 exe 打包，只读）
APP_CONFIG_FILE = "app_config.json"
DEFAULT_APP_CONFIG = {
    "app_name": "产地快打",
    "version": "v1.0.2",
    "templates": {
        "default": "JD",
        "options": [
            {"key": "JD", "label": "JD下单模板", "enabled": True},
            {"key": "JD_OFFICIAL", "label": "JD官网下单模板", "enabled": False},
            {"key": "SF", "label": "SF下单模板", "enabled": False},
        ],
    },
    "template_configs": {},
}

# 配置 Schema 定义
CONFIG_SCHEMA = {
    "wechat_keywords": list,       # list[str]
    "poll_interval_ms": int,       # 100-2000
    "auto_transfer": (bool, int),  # bool
    "double_click_copy": (bool, int),  # bool
    "auto_restore_data": (bool, int),  # bool
    "double_click_interval_ms": int,   # 200-1000
    "double_click_pos_tolerance": int,  # 5-100
    "max_errors_per_minute": int,   # 1-100
    "auto_save_interval_s": int,    # 30-3600
    "log_retention_days": int,      # 1-365
    "prefill_profiles": list,       # 预制信息档案列表
    "export_field_selection": list, # 用户勾选的导出字段
    "version": int,                 # schema version
}

DEFAULT_CONFIG = {
    "wechat_keywords": ["微信", "WeChat"],
    "poll_interval_ms": 400,
    "auto_transfer": False,
    "double_click_copy": True,
    "auto_restore_data": True,
    "double_click_interval_ms": 500,
    "double_click_pos_tolerance": 20,
    "max_errors_per_minute": 10,
    "auto_save_interval_s": 120,
    "log_retention_days": 30,
    "prefill_profiles": [],
    "export_field_selection": [],
    "version": CONFIG_VERSION,
}

# 值域约束
CONFIG_RANGES = {
    "poll_interval_ms": (100, 2000),
    "double_click_interval_ms": (200, 1000),
    "double_click_pos_tolerance": (5, 100),
    "max_errors_per_minute": (1, 100),
    "auto_save_interval_s": (30, 3600),
    "log_retention_days": (1, 365),
}


# ======================== 配置加载 ========================


def load_config() -> dict:
    """
    加载并验证配置文件。

    处理策略:
      1. 文件不存在 → 创建默认配置
      2. 文件损坏（JSON 解析失败）→ 备份损坏文件，恢复默认
      3. 配置项类型错误 → 用默认值覆盖
      4. 配置版本过旧 → 执行迁移
      5. 数值越界 → 钳制到合法范围

    Returns:
        dict: 经过验证的配置字典
    """
    if not os.path.exists(CONFIG_FILE):
        _write_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)

    # 读取文件
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # 备份损坏文件
        _backup_corrupted(str(e))
        _write_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)

    if not isinstance(raw, dict):
        _backup_corrupted("not a dict")
        _write_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)

    # 版本迁移
    version = raw.get("version", 1)
    if version < CONFIG_VERSION:
        raw = _migrate_config(raw, version)

    # 合并默认值 + 类型校验 + 范围钳制
    config = deepcopy(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key in raw:
            expected = CONFIG_SCHEMA[key]
            val = raw[key]

            # 类型校验
            if isinstance(expected, tuple):
                if isinstance(val, expected):
                    config[key] = val
                else:
                    # 尝试类型转换
                    try:
                        if bool in expected:
                            config[key] = bool(val)
                        elif int in expected:
                            config[key] = int(val)
                    except (ValueError, TypeError):
                        pass  # 保持默认值
            elif isinstance(expected, type):
                if isinstance(val, expected):
                    config[key] = val

            # 列表元素类型检查
            if key == "wechat_keywords" and isinstance(config[key], list):
                config[key] = [str(v) for v in config[key] if v]

        # 范围钳制
        if key in CONFIG_RANGES and isinstance(config[key], (int, float)):
            lo, hi = CONFIG_RANGES[key]
            config[key] = max(lo, min(hi, config[key]))

    # 确保版本号最新
    config["version"] = CONFIG_VERSION

    # 如果配置有变化，写回
    if config != raw or version != CONFIG_VERSION:
        _write_config(config)

    return config


def save_config(config: dict) -> bool:
    """
    原子写入配置文件。

    先写入临时文件，成功后再替换原文件，防止写入中断导致配置损坏。

    Returns:
        True 表示保存成功
    """
    # 补上版本号
    config = dict(config)
    config["version"] = CONFIG_VERSION

    return _write_config(config)


def reset_config() -> dict:
    """重置配置为默认值。"""
    _write_config(DEFAULT_CONFIG)
    return deepcopy(DEFAULT_CONFIG)


# ======================== 内部函数 ========================


def _write_config(config: dict) -> bool:
    """原子写入配置文件。"""
    tmp_file = CONFIG_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        # 原子替换（Windows 上 replace 覆盖现有文件）
        os.replace(tmp_file, CONFIG_FILE)
        return True
    except Exception:
        # 清理临时文件
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass
        return False


def _backup_corrupted(reason: str) -> None:
    """备份损坏的配置文件。"""
    try:
        backup_path = CONFIG_FILE + ".corrupted"
        if os.path.exists(CONFIG_FILE):
            shutil.copy2(CONFIG_FILE, backup_path)
            # 记录损坏原因
            with open(backup_path + ".txt", "w", encoding="utf-8") as f:
                f.write(f"损坏原因: {reason}\n")
    except Exception:
        pass


def _migrate_config(raw: dict, from_version: int) -> dict:
    """
    配置版本迁移。

    v1 -> v2: 新增 double_click_interval_ms, double_click_pos_tolerance,
              max_errors_per_minute, auto_save_interval_s, log_retention_days
    """
    if from_version < 2:
        # v1 没有这些字段 → 用默认值
        for key in [
            "double_click_interval_ms",
            "double_click_pos_tolerance",
            "max_errors_per_minute",
            "auto_save_interval_s",
            "log_retention_days",
        ]:
            if key not in raw:
                raw[key] = DEFAULT_CONFIG[key]

    return raw



def load_app_config() -> dict:
    """加载打包内置的应用元数据（应用名、版本号）。

    通过 resource_path 读取：源码运行时读取项目目录，
    打包后从 PyInstaller 的 _MEIPASS 临时目录读取，
    不依赖任何绝对路径；文件缺失或损坏时回退默认值。
    """
    config = deepcopy(DEFAULT_APP_CONFIG)
    try:
        with open(resource_path(APP_CONFIG_FILE), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for key in DEFAULT_APP_CONFIG:
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    config[key] = value.strip()
                elif isinstance(value, (dict, list)):
                    config[key] = deepcopy(value)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return config
