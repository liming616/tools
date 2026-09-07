"""流向产品匹配算法（独立模块，便于升级）。

规则：先市后省，rules 顺序首个命中，未命中走 fallback_product。
"""


def _hit_rule(rule: dict, province: str, city: str) -> bool:
    """判断规则是否命中：优先城市，其次省份。"""
    cities = [str(c).strip() for c in (rule.get("cities") or []) if str(c).strip()]
    provinces = [str(p).strip() for p in (rule.get("provinces") or []) if str(p).strip()]

    if cities and city and city in cities:
        return True
    if provinces and province and province in provinces:
        return True
    return False


def resolve_product(strategy: dict, province: str, city: str) -> str:
    """根据收件省/市匹配流向产品。

    遍历顺序：
      1. 含 cities 的规则（更细优先）
      2. 仅 provinces 的规则
    首个命中返回 product；全部未命中返回 fallback_product。
    """
    province = (province or "").strip()
    city = (city or "").strip()
    rules = strategy.get("rules") or []
    fallback = (strategy.get("fallback_product") or "").strip()

    # 第一遍：仅城市规则
    for rule in rules:
        cities = [str(c).strip() for c in (rule.get("cities") or []) if str(c).strip()]
        if cities and _hit_rule(rule, province, city):
            return str(rule.get("product") or "").strip()

    # 第二遍：仅省份规则
    for rule in rules:
        provinces = [str(p).strip() for p in (rule.get("provinces") or []) if str(p).strip()]
        cities = [str(c).strip() for c in (rule.get("cities") or []) if str(c).strip()]
        if provinces and not cities:
            if _hit_rule(rule, province, city):
                return str(rule.get("product") or "").strip()

    return fallback
