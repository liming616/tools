"""
Excel 模版管理器 — 加载模版表头 + 字段映射 + 数据行构建

支持 .xlsx (openpyxl) 和 .xls (xlrd) 两种格式。
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("moshidadan.template_manager")

# ======================== 默认表头 ========================

DEFAULT_HEADERS = ["姓名", "手机号", "地址"]

# ======================== 字段描述符映射表 ========================
# 格式: (field_path, 中文标签, [匹配关键词])
# field_path 支持点号分隔的嵌套路径（如 "addr.province"）

FIELD_DESCRIPTORS: list[tuple[str, str, list[str]]] = [
    ("name",           "姓名",     ["收件人姓名", "寄件人姓名", "收货人", "收件人",
                                     "客户", "联系人", "名字", "下单人", "姓名"]),
    ("phone",          "手机号",   ["收件人手机", "寄件人手机", "收件人座机", "寄件人座机",
                                     "手机号", "联系电话", "联系方式", "电话", "手机",
                                     "座机", "号码"]),
    ("province",       "省",       ["省份", "省"]),
    ("city",           "市",       ["城市", "市"]),
    ("district",       "区/县",    ["区县", "地区", "区域", "区", "县"]),
    ("township",       "街道/镇",  ["街道", "镇", "乡", "街道办"]),
    ("road",           "路/街",    ["路", "街", "大道", "巷", "弄"]),
    ("community",      "小区/村",  ["小区", "花园", "社区", "苑", "村"]),
    ("building",       "栋/楼",    ["号楼", "栋", "幢", "座"]),
    ("unit",           "单元",     ["单元", "门"]),
    ("room",           "室",       ["房号", "房间", "室"]),
    ("full_address",   "地址",     ["收件人地址", "寄件人地址", "收货地址", "收件地址",
                                     "邮寄地址", "送达地址", "详细地址", "具体地址",
                                     "地址"]),
    ("full_detail",    "详细地址",  ["详细地址", "具体地址"]),
    ("items_text",     "商品",     ["物品类型", "商品名称", "货品", "货物名称"]),
    ("notes",          "备注",     ["面单备注", "订单备注", "备注", "留言", "说明"]),
    ("raw",            "原始文本",  ["原文", "原始文本", "完整信息", "自定义信息"]),
    ("company",        "公司",     ["收件人公司", "寄件人公司", "公司", "单位", "企业"]),
    ("qq",             "QQ号",     ["QQ号", "QQ"]),
]


def load_template_headers(filepath: str) -> list[str]:
    """
    从 Excel 文件首行（或第二行，根据内容判断）读取表头。
    支持 .xlsx 和 .xls 格式。

    Returns:
        表头字符串列表（已去空白，过滤空值）
    Raises:
        ValueError: 文件无效或表头为空
    """
    if not os.path.exists(filepath):
        raise ValueError(f"文件不存在: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()

    if ext in (".xlsx", ".xlsm"):
        headers = _load_xlsx_headers(filepath)
    elif ext == ".xls":
        headers = _load_xls_headers(filepath)
    else:
        raise ValueError(f"不支持的文件格式: {ext}，仅支持 .xlsx / .xls")

    # 过滤空值并 strip
    headers = [h.strip() for h in headers if h and str(h).strip()]
    if not headers:
        raise ValueError("Excel 文件中未找到有效的表头行")

    logger.info("模版加载成功 | %s | %d 列表头", filepath, len(headers))
    return headers


def _load_xlsx_headers(filepath: str) -> list[str]:
    """从 .xlsx 文件读取表头。使用第二行（row 2），因为首行通常是合并的类别标题。"""
    import openpyxl
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    # 读取前两行来判断哪行是实际的列标题
    row1 = [_safe_cell(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    row2 = [_safe_cell(ws.cell(2, c).value) for c in range(1, ws.max_column + 1)]

    wb.close()

    # 如果 row2 有数据且 row1 看起来更像合并标题（更少非空值），使用 row2
    row1_count = sum(1 for v in row1 if v)
    row2_count = sum(1 for v in row2 if v)

    if row2_count > row1_count:
        return row2
    return row1


def _load_xls_headers(filepath: str) -> list[str]:
    """从 .xls 文件读取表头。"""
    import xlrd
    wb = xlrd.open_workbook(filepath, encoding_override='gb18030')
    ws = wb.sheet_by_index(0)

    if ws.nrows < 1:
        raise ValueError("Excel 文件为空")

    # 读取前两行，选择内容更多的作为实际表头
    row1 = [_safe_cell(ws.cell_value(0, c)) for c in range(ws.ncols)]
    row1_count = sum(1 for v in row1 if v)

    if ws.nrows >= 2:
        row2 = [_safe_cell(ws.cell_value(1, c)) for c in range(ws.ncols)]
        row2_count = sum(1 for v in row2 if v)
        if row2_count > row1_count:
            return row2

    return row1


def _safe_cell(value) -> str:
    """安全转换单元格值为字符串。"""
    if value is None:
        return ""
    s = str(value).strip()
    # 去掉 Excel 常见的前后空白和换行
    s = s.replace('\n', ' ').replace('\r', '')
    return s


# ======================== 字段映射 ========================


def map_headers_to_fields(headers: list[str]) -> list[Optional[str]]:
    """
    将表头列表映射为 field_path 列表。

    匹配策略：
    1. 精确匹配：表头与某关键词完全一致
    2. 包含匹配：表头中包含某关键词
    3. 多个匹配时，选关键词最长的（更具体）

    未匹配的列返回 None。

    Args:
        headers: Excel 表头文本列表

    Returns:
        field_path 列表（长度与 headers 相同）
    """
    mapped: list[Optional[str]] = []

    for header in headers:
        header_clean = header.strip()
        best_field = None
        best_score = 0  # 分数越高匹配越好

        for field_path, _label, keywords in FIELD_DESCRIPTORS:
            for kw in keywords:
                score = 0
                # 精确匹配：最高优先级
                if header_clean == kw:
                    score = len(kw) * 100
                # 包含匹配
                elif kw in header_clean:
                    # 短关键词（<=2字）在长表头中出现假匹配概率高，给低分
                    if len(kw) <= 2 and len(header_clean) > 4:
                        score = 0  # 忽略
                    else:
                        # 分数 = 关键词长度 / 表头长度（越精确分越高）
                        score = len(kw) * 10 * len(kw) // len(header_clean)

                if score > best_score:
                    best_score = score
                    best_field = field_path

        mapped.append(best_field if best_score > 0 else None)

    matched_count = sum(1 for f in mapped if f is not None)
    logger.debug("表头映射完成 | %d/%d 列已匹配", matched_count, len(headers))
    return mapped


def get_field_label(field_path: str) -> str:
    """获取字段的中文标签。"""
    for fp, label, _keywords in FIELD_DESCRIPTORS:
        if fp == field_path:
            return label
    return field_path


# ======================== 数据行构建 ========================


def build_row_tuple(fields: dict, mapped_fields: list[Optional[str]]) -> tuple:
    """
    根据映射关系，从 fields dict 构建 Treeview 显示行。

    Args:
        fields: 解析后的字段字典
        mapped_fields: map_headers_to_fields 的返回值

    Returns:
        字符串元组（长度 = len(mapped_fields)）
    """
    values = []
    for field_path in mapped_fields:
        if field_path is None:
            values.append("")
            continue

        value = _resolve_field(fields, field_path)
        values.append(str(value) if value else "")

    return tuple(values)


def _resolve_field(fields: dict, field_path: str) -> str:
    """从 fields dict 中按路径取值。"""
    # items_text 特殊处理
    if field_path == "items_text":
        items = fields.get("items", [])
        if not items:
            return fields.get("items_text", "")
        return "; ".join(
            f"{it.get('name', '')}×{it.get('qty', 1)}"
            for it in items
            if it.get('name')
        )

    # raw 特殊处理
    if field_path == "raw":
        return fields.get("raw", "")

    # 普通字段直接取值
    return fields.get(field_path, "")


def empty_fields_dict() -> dict:
    """返回一个所有已知字段为空的字典，作为 fields 模板。"""
    fields = {
        "name": "", "phone": "", "province": "", "city": "",
        "district": "", "township": "", "road": "", "community": "",
        "building": "", "unit": "", "room": "",
        "full_address": "", "full_detail": "",
        "items": [], "items_text": "", "notes": "", "raw": "",
        "company": "", "qq": "",
        # 地址解析特有字段（备用）
        "development_zone": "", "landmark": "",
    }
    return fields


def compute_column_width(field_path: Optional[str]) -> int:
    """根据字段类型返回建议列宽（px）。"""
    if field_path is None:
        return 70

    wide_fields = {"full_address", "full_detail", "items_text", "notes", "raw"}
    medium_fields = {"name", "phone", "province", "city", "district",
                     "township", "road", "community", "landmark",
                     "building", "unit", "room", "company"}

    if field_path in wide_fields:
        return 250
    elif field_path in medium_fields:
        return 100
    else:
        return 80
