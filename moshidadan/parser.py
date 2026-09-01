"""
订单信息解析器 - 从微信聊天文本中提取订单字段
生产版 — 带完整输入校验与异常保护

支持的格式示例:
  张三
  13812345678
  北京市朝阳区xxx路xxx号
  商品A x2
  商品B x1

  收货人：张三
  电话：13812345678
  地址：北京市朝阳区xxx路xxx号
  商品：商品A*2，商品B*1

  张三 13812345678 北京朝阳区xxx 衣服M码红色1件 裤子L码蓝色2件
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("moshidadan.parser")


@dataclass
class OrderInfo:
    """订单信息"""
    name: str = ""
    phone: str = ""
    landline: str = ""  # 座机，与手机分开存储
    address: str = ""
    items: list[dict] = field(default_factory=list)  # [{name, spec, qty, price}]
    notes: str = ""
    raw: str = ""  # 原始文本


# ---------- 预编译正则 ----------

# 手机号（中国大陆）
RE_PHONE = re.compile(r'1[3-9]\d{9}')

# 固话
RE_LANDLINE = re.compile(r'(?:\d{3,4}-)?\d{7,8}')

# 带边界的固话（避免从手机号中截取子串）
RE_LANDLINE_BOUNDED = re.compile(r'(?<!\d)(?:(?:\d{3,4}-)?\d{7,8})(?!\d)')

# 姓名模式（中文 2-4 字，前面可能有标签）
RE_NAME_TAGGED = re.compile(
    r'(?:收货人|收件人|联系人|客户|姓名|名字|下单人)[：:]\s*([一-龥]{2,4})'
)
RE_NAME_STANDALONE = re.compile(r'^([一-龥]{2,3})$', re.MULTILINE)

# 电话标签
RE_PHONE_TAGGED = re.compile(
    r'(?:电话|手机|联系方式|号码|联系电话|手机号|手机号码|联系)[：:]\s*(\d[\d\-]{6,15})'
)

# 手机标签（语义独立：只填手机字段）
RE_MOBILE_TAGGED = re.compile(
    r'(?:手机|手机号|手机号码)[：:]\s*(\d[\d\-]{6,15})'
)

# 座机标签（语义独立：只填座机字段）
RE_LANDLINE_TAGGED = re.compile(
    r'(?:座机|固话|座机电话)[：:]\s*(\d[\d\-]{6,15})'
)

# 地址标签（贪婪匹配到行尾）
RE_ADDRESS_TAGGED = re.compile(
    r'(?:地址|收货地址|收件地址|邮寄地址|送达地址|详细地址)[：:]\s*(.+)'
)

# 省份开头匹配地址（无标签情况）
PROVINCES = "北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆|内蒙古"
RE_ADDRESS_PROVINCE = re.compile(
    rf'((?:{PROVINCES})(?:省|市|自治区|特别行政区)?[一-龥\dA-Za-z]+(?:市|区|县|镇|乡|村|路|街|道|巷|号|楼|栋|单元|室|层|座|弄|园|苑|小区|大厦|广场|公寓|花园)[一-龥\dA-Za-z\-]*)'
)

# 商品行模式
RE_PRODUCT_LINE = re.compile(
    r'(?:商品|产品|货物|物品|下单|订单|购买|订购)[：:]\s*(.+)'
)

# 单个商品提取: "商品名 x2" / "商品名*2" / "商品名 2件/个/盒/箱"
RE_ITEM_QTY = re.compile(
    r'([一-龥a-zA-Z0-9\s\w]+?)\s*[xX\*×]\s*(\d+)'
)
RE_ITEM_QTY_CN = re.compile(
    r'([一-龥a-zA-Z0-9]+?)\s*(\d+)\s*(?:件|个|盒|箱|套|双|条|瓶|袋|包|斤|公斤|千克|吨|把|只|本|台|部|支|张|块|颗|粒)'
)

# 中文数字（用于识别「两箱」「三斤」这类中文数量）
CN_NUM_CHARS = "零〇一二两三四五六七八九十百千万"

# 量词（件/个/箱/斤/条…，用于区分物品与姓名）
MEASURE_WORDS = "件个盒箱套双条瓶袋包斤公斤千克吨把只本台部支张块颗粒"

# 中文数量 + 量词（如「两箱大桃」→ 大桃 x2）
RE_ITEM_QTY_CN_NUM = re.compile(
    rf'^([{CN_NUM_CHARS}]+)\s*([{MEASURE_WORDS}]+)\s*(.+)$'
)

# 常见姓氏（用于 4 字 token 的姓名/物品判别）
COMMON_SURNAMES = set(
    "王李张刘陈杨赵黄周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖"
    "田董潘袁蔡蒋余于杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付"
    "方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向"
    "汤成康施文洪"
)

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _cn_num_to_int(s: str) -> Optional[int]:
    """中文数字转整数（一到九千九百九十九）。无法解析返回 None。"""
    if not s:
        return None
    total = 0
    section = 0
    number = 0
    for ch in s:
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if number == 0:
                number = 1  # 处理「十」「十五」等
            section += number * unit
            number = 0
            if unit == 10000:
                total += section * 10000
                section = 0
        else:
            return None
    total += section + number
    return total if total > 0 else None


def _match_name_candidate(tok: str) -> Optional[str]:
    """判断 token 是否像姓名，返回去掉尾随数字后的姓名；不像则返回 None。

    用于「地址 电话 姓名 物品」同行格式中，区分姓名与物品信息：
      - 「李明」「王五」→ 姓名
      - 「两箱大桃」「三斤苹果」→ 物品（中文数字 + 量词开头）
    """
    m = re.match(r'^([一-龥]{2,4})\d*$', tok)
    if not m:
        return None
    name = m.group(1)
    # 「中文数字 + 量词」开头（两箱/三斤/五件…）→ 物品，不是姓名
    if re.search(rf'^[{CN_NUM_CHARS}]+[{MEASURE_WORDS}]', name):
        return None
    if name[0] in COMMON_SURNAMES:
        return name
    if len(name) <= 3:
        return name
    return None  # 4 字且非常见姓氏 → 更像物品

# 备注标签
RE_NOTES = re.compile(
    r'(?:备注|留言|说明|要求|注意|标注|备忘)[：:]\s*(.+)'
)

# ---------- 置信度评分 ----------

# 姓名黑名单：这些词不应被当作人名（用于降低误识别置信度）
NAME_BLACKLIST = {
    "总部", "号楼", "收件", "收货", "收件人", "收货人", "联系人", "地址",
    "电话", "手机", "微信", "下单", "商品", "备注", "快递", "发货",
    "订单", "购买", "客户", "联系方式", "经理", "仓库", "门店", "中心",
    "基地", "园区", "开发区", "有限公司", "公司", "厂区", "物流",
}

# 总体置信度低于该阈值时，UI 高亮提示人工核对
LOW_CONFIDENCE_THRESHOLD = 0.6

# 手机号/固话的精确全匹配
RE_PHONE_FULLMATCH = re.compile(r'1[3-9]\d{9}')
RE_LANDLINE_FULLMATCH = re.compile(r'(?:\d{3,4}-)?\d{7,8}')

# 地址中出现的结构关键词（用于判断地址完整度）
RE_ADDR_KEYWORD = re.compile(
    r'(市|区|县|镇|乡|村|路|街|道|巷|号|楼|栋|单元|室|层|座|弄|园|苑|小区|大厦|广场|公寓|花园)'
)


def _classify_phone(value: str) -> str:
    """区分手机号与座机：返回 'mobile' / 'landline' / ''。"""
    v = str(value or "").strip()
    if RE_PHONE_FULLMATCH.fullmatch(v):
        return "mobile"
    if RE_LANDLINE_FULLMATCH.fullmatch(v):
        return "landline"
    return ""


def parse_order(text: str) -> OrderInfo:
    """
    从一段文本中解析出订单信息。

    解析策略（按优先级）：
    1. 标签匹配（收货人：xxx、电话：xxx、地址：xxx）
    2. 模式匹配（手机号正则、地址正则）
    3. 位置推断（第一行可能是姓名）
    """
    if not text or not text.strip():
        return OrderInfo(raw=text)

    text = text.strip()
    order = OrderInfo(raw=text)
    consumed_ranges: list[tuple[int, int]] = []

    def mark_consumed(m: re.Match) -> None:
        consumed_ranges.append((m.start(), m.end()))

    # --- 1. 标签提取 ---

    # 姓名（标签）
    m = RE_NAME_TAGGED.search(text)
    if m:
        order.name = m.group(1)
        mark_consumed(m)

    # 电话（标签）：手机/座机语义分开，互不赋值
    m = RE_MOBILE_TAGGED.search(text)
    if m:
        order.phone = m.group(1)
        mark_consumed(m)

    m = RE_LANDLINE_TAGGED.search(text)
    if m:
        order.landline = m.group(1)
        mark_consumed(m)

    m = RE_PHONE_TAGGED.search(text)
    if m and not _is_in_consumed(m, consumed_ranges):
        phone_value = m.group(1)
        if _classify_phone(phone_value) == "landline":
            order.landline = order.landline or phone_value
        else:
            order.phone = order.phone or phone_value
        mark_consumed(m)

    # 地址（标签）
    m = RE_ADDRESS_TAGGED.search(text)
    if m:
        order.address = m.group(1).strip()
        mark_consumed(m)

    # 商品（标签）
    m = RE_PRODUCT_LINE.search(text)
    if m:
        order.items = parse_items(m.group(1))
        mark_consumed(m)

    # 备注（标签）
    m = RE_NOTES.search(text)
    if m:
        order.notes = m.group(1).strip()
        mark_consumed(m)

    # --- 2. 无标签时用正则兜底 ---

    # 手机号（全局扫描）
    if not order.phone:
        for m in RE_PHONE.finditer(text):
            if not _is_in_consumed(m, consumed_ranges):
                order.phone = m.group()
                break

    # 座机（全局扫描，带边界避免截取手机号子串）
    if not order.landline:
        for m in RE_LANDLINE_BOUNDED.finditer(text):
            if not _is_in_consumed(m, consumed_ranges):
                order.landline = m.group()
                break

    # 地址（省份匹配）
    if not order.address:
        m = RE_ADDRESS_PROVINCE.search(text)
        if m:
            order.address = m.group(1)

    # --- 2b. 「地址 电话 姓名 物品」同行格式 ---
    # 例："北京市大兴区亦庄经济开发区京东总部2号楼 15811111111 李明 两箱大桃"
    # 地址提取成功后，从地址之后的文本拆出电话、姓名和物品。
    # 不依赖 order.phone 是否为空，避免手机号识别失败导致姓名也解析不到。
    if order.address:
        addr_pos = text.find(order.address)
        if addr_pos >= 0:
            addr_end = addr_pos + len(order.address)
            # 只取地址所在「同一行」的剩余部分，避免跨行把后续商品行误当作姓名
            line_end = text.find('\n', addr_end)
            if line_end < 0:
                line_end = len(text)
            tail = text[addr_end:line_end].strip()
            if tail:
                tokens = [t for t in re.split(r'[\s，,、;；]+', tail) if t]
                # 电话：末尾的数字串（支持 7-15 位，含区号连字符），手机/座机分别写入
                if not order.phone or not order.landline:
                    for tok in reversed(tokens):
                        if not re.fullmatch(r'(?:\d{3,4}-)?\d{7,15}', tok):
                            continue
                        kind = _classify_phone(tok)
                        if kind == "landline" and not order.landline:
                            order.landline = tok
                        elif kind == "mobile" and not order.phone:
                            order.phone = tok
                        elif not order.phone and not order.landline:
                            order.phone = tok  # 无法分类时兼容旧行为
                        if order.phone and order.landline:
                            break
                # 姓名：首个「像姓名」的 token（排除物品描述，如「两箱大桃」）
                if not order.name:
                    for tok in tokens:
                        if tok in (order.phone, order.landline):
                            continue
                        name = _match_name_candidate(tok)
                        if name:
                            order.name = name
                            break
                # 物品：电话/姓名之外的剩余 token
                if not order.items:
                    for tok in tokens:
                        if tok in (order.phone, order.landline):
                            continue
                        if order.name and re.fullmatch(re.escape(order.name) + r'\d*', tok):
                            continue
                        # 跳过地址尾段残留（路/街/巷/号/楼/栋/区/苑/园等，且无量词）
                        if re.search(r'[路街巷号栋楼座单元室区苑园]', tok) and not re.search(rf'[{MEASURE_WORDS}]', tok):
                            continue
                        for it in parse_items(tok):
                            order.items.append(it)

    # 兜底：姓名仍为空但已识别到电话时，从「电话之前、地址之后」取中文姓名
    # （适用于地址与姓名之间无空格的情况，如 "北京市...1号楼李明 15811171111"）
    if not order.name and (order.phone or order.landline):
        phone_text = order.phone or order.landline
        phone_pos = text.find(phone_text)
        if phone_pos > 0:
            before_phone = text[:phone_pos].rstrip()
            if order.address:
                addr_pos = text.find(order.address)
                if addr_pos >= 0:
                    between = text[addr_pos + len(order.address):phone_pos].strip()
                    # 允许姓名带尾随数字（如 "李明1"）
                    m = re.match(r'^([一-龥]{2,4})\d*$', between)
                    if m:
                        order.name = m.group(1)
            if not order.name:
                # 兜底：提取电话前末尾的中文2-4字作为姓名（允许尾随数字）
                m = re.search(r'(?<![一-龥])([一-龥]{2,4})\d*\s*$', before_phone)
                if m:
                    order.name = m.group(1)

    # --- 3. 行级解析：把单行姓名和单行商品找出来 ---

    lines = text.split('\n')
    remaining_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        remaining_lines.append(stripped)

    # 无标签姓名：第一行中文 2-3 字且无冒号
    if not order.name and remaining_lines:
        first = remaining_lines[0]
        if RE_NAME_STANDALONE.match(first):
            order.name = first
            remaining_lines = remaining_lines[1:]
        else:
            # 同行格式：「姓名 电话 地址 商品...」
            # 尝试提取电话号码前的中文作为姓名
            phone_match = RE_PHONE.search(first)
            if not phone_match:
                phone_match = RE_LANDLINE_BOUNDED.search(first)
            if phone_match:
                prefix = first[:phone_match.start()].strip()
                m = re.match(r'^([一-龥]{2,4})$', prefix)
                if m:
                    order.name = m.group(1)

    # 无标签商品：逐行尝试提取商品，且用空格分割单行
    if not order.items:
        for line in remaining_lines:
            # 跳过姓名行（避免把姓名当商品，兼容「李四1」这类带尾随数字）
            if order.name and re.fullmatch(re.escape(order.name) + r'\d*', line.strip()):
                continue
            # 跳过看起来像电话号码或地址的行
            if _is_phone_or_addr_line(line):
                continue

            # 如果行中无逗号/顿号但有空格，按空格分段
            if not re.search(r'[，,、;；。]', line) and ' ' in line:
                # 单行空格分割格式：取地址后面的部分作为商品
                # 已知电话和地址后，剩余部分多半是商品
                segments = _split_after_address(
                    line, order.address, order.phone, order.landline
                )
                for seg in segments:
                    # 跳过地址残留片段
                    if order.address and seg.strip() in order.address:
                        continue
                    items = parse_items(seg)
                    if items:
                        order.items.extend(items)
            else:
                items = parse_items(line)
                if items:
                    order.items.extend(items)

    return order


def is_blacklisted_name(name: str) -> bool:
    """判断姓名是否疑似误识别（含黑名单词）。"""
    if not name:
        return False
    return any(tok in name for tok in NAME_BLACKLIST)


def score_fields(fields: dict) -> tuple[float, list[str], dict]:
    """
    对解析出的订单字段做置信度评分，用于低置信度高亮与人工纠错。

    评分维度: 姓名 / 手机号 / 地址，各返回 0.0~1.0。
    总体置信度为三者加权平均（姓名 0.3 + 手机号 0.3 + 地址 0.4）。

    Args:
        fields: 统一字段 dict（含 name / phone / full_address 等键）

    Returns:
        (overall, warnings, scores)
        overall  : 0.0 ~ 1.0
        warnings : 人类可读的中文警告列表（可能为空）
        scores   : {"name": float, "phone": float, "address": float}
    """
    name = (fields.get("name") or "").strip()
    phone = (fields.get("phone") or "").strip()
    landline = (fields.get("landline") or "").strip()
    address = (fields.get("full_address") or "").strip()

    warnings: list[str] = []
    scores = {"name": 0.0, "phone": 0.0, "address": 0.0}

    # --- 姓名 ---
    if not name:
        scores["name"] = 0.0
        warnings.append("姓名缺失")
    elif is_blacklisted_name(name):
        scores["name"] = 0.1
        warnings.append(f"姓名疑似误识别（{name}）")
    elif re.fullmatch(r'[一-龥]{2,3}', name):
        scores["name"] = 0.9
    elif re.fullmatch(r'[一-龥]{4}', name):
        scores["name"] = 0.7
    elif re.fullmatch(r'[一-龥]{2,4}\d{1,2}', name) or re.search(r'\d', name):
        scores["name"] = 0.4
    else:
        scores["name"] = 0.5

    # --- 手机号/座机（任一有效即可，手机优先）---
    if not phone and not landline:
        scores["phone"] = 0.0
        warnings.append("手机号缺失")
    elif phone and RE_PHONE_FULLMATCH.fullmatch(phone):
        scores["phone"] = 0.95
    elif phone and RE_LANDLINE_FULLMATCH.fullmatch(phone):
        scores["phone"] = 0.6
        warnings.append(f"疑似固话（{phone}）")
    elif landline and RE_LANDLINE_FULLMATCH.fullmatch(landline):
        scores["phone"] = 0.6
        warnings.append(f"仅固话（{landline}）")
    elif phone and re.fullmatch(r'\d{6,15}', phone):
        scores["phone"] = 0.5
        warnings.append(f"手机号长度异常（{phone}）")
    elif landline and re.fullmatch(r'\d{6,15}', landline):
        scores["phone"] = 0.5
        warnings.append(f"座机号长度异常（{landline}）")
    elif phone:
        scores["phone"] = 0.3
        warnings.append(f"手机号格式异常（{phone}）")
    else:
        scores["phone"] = 0.3
        warnings.append(f"座机号格式异常（{landline}）")

    # --- 地址 ---
    if not address:
        scores["address"] = 0.0
        warnings.append("地址缺失")
    else:
        has_province = RE_ADDRESS_PROVINCE.search(address) is not None
        has_keyword = RE_ADDR_KEYWORD.search(address) is not None
        if has_province and has_keyword:
            scores["address"] = 0.95
        elif has_province:
            scores["address"] = 0.6
            warnings.append("地址不完整（仅识别到省市）")
        elif len(address) >= 8 and has_keyword:
            scores["address"] = 0.8
        elif len(address) >= 4:
            scores["address"] = 0.4
            warnings.append("地址可能不完整")
        else:
            scores["address"] = 0.3
            warnings.append("地址过短，可能不完整")

    overall = round(
        scores["name"] * 0.3 + scores["phone"] * 0.3 + scores["address"] * 0.4,
        3,
    )
    return overall, warnings, scores


def is_low_confidence(overall: float, scores: dict) -> bool:
    """判断一行是否应被标记为低置信度（供 UI 高亮）。

    任一核心字段缺失 / 姓名误识别 / 总体过低，均视为低置信度，
    避免把错误数据静默写入。
    """
    if overall < LOW_CONFIDENCE_THRESHOLD:
        return True
    if scores.get("name", 1.0) < 0.2:      # 姓名缺失或黑名单误识别
        return True
    if scores.get("phone", 1.0) == 0.0:    # 手机号缺失
        return True
    if scores.get("address", 1.0) == 0.0:  # 地址缺失
        return True
    return False


def parse_items(text: str, skip_phone_addr: bool = True) -> list[dict]:
    """
    从商品描述文本中提取商品列表。

    示例输入:
      "衣服M码红色 2件，裤子L码蓝色 1件"
      "商品A x2, 商品B*3"
      "苹果 5斤，香蕉 3把"
    输出:
      [{"name": "衣服M码红色", "qty": 2}, ...]
    """
    items = []
    if not text:
        return items

    # 按中英文逗号、顿号分割（如果没有逗号但有空格，则按空格分割）
    if re.search(r'[，,、;；。]', text):
        segments = re.split(r'[，,、;；。\n]', text)
    elif ' ' in text:
        segments = text.split(' ')
    else:
        segments = [text]

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # 跳过看起来像电话号码的段
        if skip_phone_addr and (RE_PHONE.match(seg) or RE_LANDLINE.fullmatch(seg)):
            continue
        # 跳过看起来像地址的段（含省份关键词）
        if skip_phone_addr and RE_ADDRESS_PROVINCE.match(seg):
            continue

        qty = 1
        name = seg

        # 尝试 "中文数字+量词" 格式（如「两箱大桃」→ 大桃 x2）
        m = RE_ITEM_QTY_CN_NUM.match(seg)
        if m:
            num = _cn_num_to_int(m.group(1))
            rest = m.group(3).strip()
            if num is not None and rest:
                name = rest
                qty = num
        else:
            # 尝试 "商品名 x2" 格式
            m = RE_ITEM_QTY.search(seg)
            if m:
                name = m.group(1).strip()
                qty = int(m.group(2))
            else:
                # 尝试 "商品名 2件" 格式
                m = RE_ITEM_QTY_CN.search(seg)
                if m:
                    name = m.group(1).strip()
                    qty = int(m.group(2))

        # 去掉名称两端的无意义字符
        name = name.strip('，,。.、 \t*×xX')

        if name:
            items.append({
                "name": name, "spec": "", "qty": qty, "price": 0.0,
                "raw": seg,
            })

    return items


def _is_phone_or_addr_line(line: str) -> bool:
    """判断一行是否看起来像电话号码或地址（不应作为商品解析）。"""
    stripped = line.strip()
    # 纯数字（含连字符）可能是电话
    if re.match(r'^[\d\-]+$', stripped):
        return True
    # 手机号 / 座机
    if RE_PHONE.fullmatch(stripped) or RE_LANDLINE.fullmatch(stripped):
        return True
    # 省份开头的地址
    if RE_ADDRESS_PROVINCE.match(stripped):
        return True
    return False


def _split_after_address(text: str, address: str, phone: str,
                         landline: str = "") -> list[str]:
    """在单行文本中，提取地址后面的商品部分。"""
    # 尝试在电话号码后分割（优先级更高，因为电话更精确）
    if phone and phone in text:
        idx = text.find(phone) + len(phone)
        remaining = text[idx:].strip()
        # 剩余部分可能仍有地址尾段，尝试用空格进一步切分
        if remaining:
            return [remaining]
        return [text]

    if landline and landline in text:
        idx = text.find(landline) + len(landline)
        remaining = text[idx:].strip()
        if remaining:
            return [remaining]
        return [text]

    if address and address in text:
        idx = text.find(address) + len(address)
        remaining = text[idx:].strip()
        # 地址后面的内容：按空格切分后过滤掉明显是地址尾段的（如 "xx路xx号"）
        if ' ' in remaining:
            parts = remaining.split(' ')
            # 过滤掉含"路"、"号"、"街"、"巷"且无商品数量标记的部分
            result = []
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if re.search(r'[路街巷号栋楼座]', p) and not re.search(r'[xX\*×\d]', p):
                    continue  # 地址尾段，跳过
                result.append(p)
            if result:
                return [' '.join(result)]
        if remaining and not re.match(r'^[路街巷号栋楼座\d]+$', remaining):
            return [remaining]

    return [text]


def _is_in_consumed(m: re.Match, ranges: list[tuple[int, int]]) -> bool:
    """检查匹配是否在已消费范围内。"""
    s, e = m.start(), m.end()
    return any(cs <= s and e <= ce for cs, ce in ranges)


# ---------- 格式化输出 ----------

def format_for_order_software(order: OrderInfo) -> str:
    """格式化为打单软件可用的文本（适合粘贴到 Excel/ERP）。"""
    parts = []
    if order.name:
        parts.append(f"收货人：{order.name}")
    if order.phone:
        parts.append(f"电话：{order.phone}")
    if order.landline:
        parts.append(f"座机：{order.landline}")
    if order.address:
        parts.append(f"地址：{order.address}")
    if order.items:
        item_lines = "\n".join(
            f"  {i+1}. {it['name']}  ×{it['qty']}"
            + (f"  ¥{it['price']:.2f}" if it['price'] else "")
            for i, it in enumerate(order.items)
        )
        parts.append(f"商品：\n{item_lines}")
    if order.notes:
        parts.append(f"备注：{order.notes}")

    return "\n".join(parts)


def format_tsv(order: OrderInfo) -> str:
    """格式化为 TSV（Tab 分隔，可粘贴到 Excel）。"""
    name = order.name
    phone = order.phone or order.landline
    addr = order.address
    notes = order.notes
    items_str = "; ".join(f"{it['name']}×{it['qty']}" for it in order.items)

    return f"{name}\t{phone}\t{addr}\t{items_str}\t{notes}"


# ---------- 测试 ----------

if __name__ == "__main__":
    samples = [
        # 格式1：标签格式
        """收货人：张三
电话：13812345678
地址：北京市朝阳区望京街道xxx小区3号楼2单元501
商品：衣服M码红色 2件，裤子L码蓝色 1件
备注：周末配送""",

        # 格式2：简短格式
        """李四
13987654321
广东省深圳市南山区科技园xx路xx号
苹果 5斤，香蕉 3把""",

        # 格式3：同行格式
        "王五 13611112222 上海市浦东新区陆家嘴xx路xx号 键盘x2 鼠标x1",
    ]

    for i, s in enumerate(samples, 1):
        print(f"\n{'='*50}")
        print(f"样本 {i}:")
        print(s)
        print(f"\n解析结果:")
        order = parse_order(s)
        print(f"  姓名: {order.name}")
        print(f"  电话: {order.phone}")
        print(f"  座机: {order.landline}")
        print(f"  地址: {order.address}")
        print(f"  商品: {order.items}")
        print(f"  备注: {order.notes}")
        print(f"\n格式化输出:")
        print(format_for_order_software(order))


# ======================== 安全解析包装 ========================


def parse_order_safe(text: str) -> OrderInfo:
    """
    安全解析订单信息 — 带异常保护和日志。

    此函数保证永远不会抛出异常，适合在生产环境调用。
    解析失败时返回空的 OrderInfo（raw 保留原始文本）。

    Args:
        text: 待解析的文本

    Returns:
        OrderInfo 实例（保证不为 None）
    """
    if not text or not isinstance(text, str):
        logger.debug("parse_order_safe: 输入为空或非字符串类型")
        return OrderInfo(raw=str(text) if text else "")

    # 长度限制（防止恶意超长文本）
    if len(text) > 100000:
        logger.warning("parse_order_safe: 输入文本过长(%d字符)，截断处理", len(text))
        text = text[:100000]

    try:
        return parse_order(text)
    except re.error as e:
        logger.error("parse_order_safe: 正则错误 — %s", e)
        return OrderInfo(raw=text[:1000])
    except Exception as e:
        logger.exception("parse_order_safe: 解析异常 — %s", e)
        return OrderInfo(raw=text[:1000])


def parse_items_safe(text: str) -> list[dict]:
    """
    安全解析商品列表 — 带异常保护。

    Returns:
        list[dict]: 保证不为 None，解析失败返回空列表
    """
    try:
        return parse_items(text)
    except Exception as e:
        logger.warning("parse_items_safe: 商品解析异常 — %s", e)
        return []
