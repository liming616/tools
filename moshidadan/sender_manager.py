"""寄件人管理：1/2/3 档案 + 默认寄件人 + 流向策略选中。"""

from typing import Optional


class SenderManager:
    """管理寄件人 1/2/3 与默认寄件人，提供字段兜底与策略选中。"""

    def __init__(self, config: dict):
        self._config = config or {}
        self._profiles = self._config.get("sender_profiles") or []
        self._default = self._config.get("default_sender") or {}

    def _selected(self) -> Optional[dict]:
        selected = (self._config.get("selected_sender") or "").strip()
        for p in self._profiles:
            if (p.get("label") or "") == selected:
                return p
        return None

    def _pick(self, key: str) -> str:
        sel = self._selected()
        if sel:
            value = str(sel.get(key) or "").strip()
            if value:
                return value
        return str(self._default.get(key) or "").strip()

    def get_selected_sender_fields(self) -> dict:
        """返回合并后的寄件人字段（选中优先，空字段兜底默认）。"""
        return {
            "sender_name": self._pick("sender_name"),
            "sender_phone": self._pick("sender_phone"),
            "sender_landline": self._pick("sender_landline"),
            "sender_address": self._pick("sender_address"),
            "sender_company": self._pick("sender_company"),
            "sender_warehouse_code": self._pick("sender_warehouse_code"),
        }

    def get_temperature_layer(self) -> str:
        """温层：选中寄件人优先，空则默认。"""
        return self._pick("temperature_layer")

    def get_payment_method(self, template_key: str) -> str:
        """付款方式/支付方式：选中寄件人优先，空则默认。"""
        return self._pick("payment_method")

    def get_selected_strategy_id(self, template_key: str) -> str:
        """读取指定模板选中的流向策略 id。"""
        selected = self._config.get("selected_strategy") or {}
        return str(selected.get(template_key) or "").strip()

    def set_selected_strategy(self, template_key: str, strategy_id: str) -> None:
        """写入指定模板选中的流向策略 id。"""
        selected = self._config.setdefault("selected_strategy", {})
        selected[template_key] = strategy_id
