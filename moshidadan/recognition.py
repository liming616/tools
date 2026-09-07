"""文本识别壳层：规范化 + 按行识别 + 未识别归位到备注。"""

import re

from address_parser import parse_address_safe
from parser import parse_order_safe

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """将所有换行与连续空白替换为单空格，并去除首尾空白。"""
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text).strip()


def recognize_line(line: str) -> dict:
    """识别单行文本，返回 fields dict。"""
    parsed = parse_order_safe(line)
    addr = parse_address_safe(parsed.address or line)
    items_text = ""
    for item in getattr(parsed, "items", []) or []:
        name = str(item.get("raw") or item.get("name") or "").strip()
        if name:
            items_text = (items_text + "; " + name) if items_text else name

    fields = {
        "name": (parsed.name or "").strip(),
        "phone": (parsed.phone or "").strip(),
        "landline": (parsed.landline or "").strip(),
        "full_address": addr.full_address or (parsed.address or "").strip(),
        "province": addr.province or "",
        "city": addr.city or "",
        "district": addr.district or "",
        "items_text": items_text,
        "delivery_product": "",
        "temperature_layer": "",
        "payment_method": "",
        "item_count": "",
        "notes": (parsed.notes or "").strip(),
    }
    # 未识别到有效收件人信息（姓名/手机/座机，或解析出省/市行政区域）时，
    # 把疑似商品/普通文本归入面单备注，而不是作为物品类型。
    # 注意：full_address 对无法识别省份的文本会被 address_parser 整体兜底，
    # 因此不作为有效收件人的判定依据。
    has_receiver_info = any(
        fields[k] for k in ("name", "phone", "landline")
    ) or bool(fields["province"] or fields["city"])
    if not has_receiver_info and fields["items_text"]:
        fields["notes"] = (fields["notes"] + "; " + fields["items_text"]).strip("; ")
        fields["items_text"] = ""
    return fields


def recognize_batch(text: str) -> list:
    """按非空行分段，逐行识别，返回 fields dict 列表。"""
    result = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            result.append(recognize_line(line))
    return result
