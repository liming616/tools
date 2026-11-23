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
    """识别单行文本，返回收件人字段、结构化地址和统一备注。"""
    parsed = parse_order_safe(line)
    addr = parse_address_safe(parsed.address or line)
    raw_item_texts = [
        str(item.get("raw") or item.get("name") or "").strip()
        for item in (getattr(parsed, "items", []) or [])
        if str(item.get("raw") or item.get("name") or "").strip()
    ]
    fields = {
        "name": (parsed.name or "").strip(),
        "phone": (parsed.phone or "").strip(),
        "landline": (parsed.landline or "").strip(),
        "full_address": addr.full_address or (parsed.address or "").strip(),
        "province": addr.province or "",
        "city": addr.city or "",
        "district": addr.district or "",
        "items": [],
        "items_text": "",
        "delivery_product": "",
        "temperature_layer": "",
        "payment_method": "",
        "item_count": "",
        "notes": merge_note_fragments(parsed.notes, *raw_item_texts),
    }
    return fields


def recognize_batch(text: str) -> list:
    """按非空行分段，逐行识别，返回 fields dict 列表。"""
    result = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            result.append(recognize_line(line))
    return result


def merge_note_fragments(*fragments) -> str:
    """拆分、去标签并去重备注片段。"""
    result = []
    seen = set()
    for fragment in fragments:
        text = str(fragment or "")
        parts = re.split(
            r"[;\n]+|\s+(?=(?:备注|留言|说明|要求|注意|标注|备忘)[：:])",
            text,
        )
        for part in parts:
            part = re.sub(
                r"^(?:备注|留言|说明|要求|注意|标注|备忘)[：:]\s*",
                "",
                part.strip(),
            )
            part = re.sub(r"\s+", " ", part).strip()
            if not part:
                continue
            key = part.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(part)
    return "; ".join(result)
