"""未导出数据持久化：按模板分组存储，确保切换模板回显、重启后恢复。"""

import json
import os

from paths import app_dir


_DEFAULT_KEY = "__default__"


def _data_file() -> str:
    """返回未导出数据文件路径。"""
    return os.path.join(app_dir(), "collected_data.json")


def _read_store() -> dict:
    """读取整个存储文件，失败或缺失返回空 dict。"""
    path = _data_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_store(data: dict) -> bool:
    """原子写回存储文件。"""
    path = _data_file()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def _ensure_groups(data: dict) -> dict:
    """保证 items_by_template 字典存在；旧格式 items_by_template 缺失时初始化。"""
    if not isinstance(data.get("items_by_template"), dict):
        data["items_by_template"] = {}
    return data


def _migrate_legacy_to(template_key: str, old_rows: list) -> None:
    """把旧版全局 items 迁移到指定模板分支。"""
    data = _read_store()
    data = _ensure_groups(data)
    if not data["items_by_template"] and old_rows:
        data["items_by_template"][template_key] = old_rows
        _write_store(data)


def save_collected_by_template(template_key: str, rows: list) -> bool:
    """按模板原子保存未导出列表数据。"""
    data = _read_store()
    data = _ensure_groups(data)
    data["items_by_template"][template_key] = rows or []
    return _write_store(data)


def load_collected_by_template(template_key: str) -> list:
    """按模板加载未导出数据，失败返回空列表。"""
    data = _read_store()
    groups = data.get("items_by_template")
    if isinstance(groups, dict):
        rows = groups.get(template_key)
        return rows if isinstance(rows, list) else []
    # 旧版全局 items：迁移给当前模板，避免旧数据丢失
    old_rows = data.get("items")
    if isinstance(old_rows, list) and old_rows:
        _migrate_legacy_to(template_key, old_rows)
        return old_rows
    return []


def clear_collected_by_template(template_key: str) -> bool:
    """清空指定模板的数据分组。"""
    data = _read_store()
    groups = data.get("items_by_template")
    if isinstance(groups, dict) and template_key in groups:
        del groups[template_key]
        return _write_store(data)
    return False


# ======================== 兼容旧接口 ========================


def save_collected(rows: list) -> bool:
    """兼容旧接口：保存到默认分组。"""
    return save_collected_by_template(_DEFAULT_KEY, rows)


def load_collected() -> list:
    """兼容旧接口：读取默认分组；旧格式 items 直接返回。"""
    data = _read_store()
    groups = data.get("items_by_template")
    if isinstance(groups, dict):
        rows = groups.get(_DEFAULT_KEY)
        return rows if isinstance(rows, list) else []
    old_rows = data.get("items")
    return old_rows if isinstance(old_rows, list) else []


def clear_collected() -> bool:
    """兼容旧接口：清空整个未导出数据文件。"""
    path = _data_file()
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False
