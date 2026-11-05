
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ValidationError

from src.config.auth import AuthConfig
from src.config.auth_loader import parse_block, relay_block
from src.config.catalog import CatalogConfig
from src.config.providers import ProvidersConfig
from src.config.rate_limits import AuthRateLimits

Rows = List[Dict[str, Any]]
Guard = Callable[[Any, Any], Rows]

Rule = Callable[[Any, Any], bool]

Reader = Callable[[Any], BaseModel]

ADDRESS = "address"
TRUST = "trust"


def _changed_text(old: Any, new: Any) -> bool:
    return bool(new) and new != old


def _any_change(old: Any, new: Any) -> bool:
    return new != old


def _raised(old: Any, new: Any) -> bool:
    return new > old


def _switched_on(old: Any, new: Any) -> bool:
    return bool(new) and not old


def _show(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _loader_reader(model: type, event: str) -> Reader:
    def read(raw: Any) -> BaseModel:
        return parse_block(model, raw or {}, event=event)
    return read


def _loads(model: type, raw: Any) -> bool:
    try:
        model(**(raw or {}))
    except (ValidationError, TypeError):
        return False
    return True


def _unread_rows(
    prefix: str, rules: Tuple[Tuple[str, Rule, str], ...], old: BaseModel, before: Any, after: Any
) -> Rows:
    wrote = after if isinstance(after, Mapping) else {}
    held = before if isinstance(before, Mapping) else {}
    return [_row(f"{prefix}.{field}", kind, field, _show(wrote[field]), _show(getattr(old, field)))
            for field, _rule, kind in rules if field in wrote and wrote[field] != held.get(field)]


def block_guard(reader: Reader, prefix: str, rules: Tuple[Tuple[str, Rule, str], ...]) -> Guard:
    def guard(before: Any, after: Any) -> Rows:
        old, new = reader(before), reader(after)
        if not _loads(type(new), after):
            return _unread_rows(prefix, rules, old, before, after)
        rows: Rows = []
        for field, rule, kind in rules:
            old_value, new_value = getattr(old, field), getattr(new, field)
            if new_value == type(new).model_fields[field].default and isinstance(new_value, str):
                continue
            if rule(old_value, new_value):
                rows.append(_row(f"{prefix}.{field}", kind, field, _show(new_value), _show(old_value)))
        return rows
    return guard


def _row(row_id: str, kind: str, field: str, text: str, was: Optional[str]) -> Dict[str, Any]:
    return {"id": row_id, "kind": kind, "label": row_id, "parts": [{"kind": field, "text": text, "was": was}]}


_RELAY_RULES = (
    ("url", _changed_text, ADDRESS), ("control_url", _changed_text, ADDRESS),
    ("link_tunnel_url", _changed_text, ADDRESS), ("link_domain", _changed_text, ADDRESS),
    ("link_acme_directory", _changed_text, ADDRESS), ("enabled", _switched_on, TRUST),
)

written_relay = block_guard(relay_block, "relay", _RELAY_RULES)
written_catalog = block_guard(_loader_reader(CatalogConfig, "invalid_catalog_config_block"), "catalog", (
    ("api_base_url", _changed_text, ADDRESS), ("index_url", _changed_text, ADDRESS)))
written_rate_limits = block_guard(
    _loader_reader(AuthRateLimits, "invalid_auth_rate_limits_block"), "auth_rate_limits", (
    ("trust_proxy_headers", _any_change, TRUST), ("totp_verify_per_minute", _raised, TRUST),
    ("totp_verify_per_hour", _raised, TRUST)))
written_providers = block_guard(_loader_reader(ProvidersConfig, "invalid_providers_config_block"), "providers", (
    ("local_host", _changed_text, ADDRESS),))


def _loaded_int(raw: Any, default: int) -> Optional[int]:
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def ttl_guard(name: str) -> Guard:
    default = AuthConfig.model_fields[name].default

    def guard(before: Any, after: Any) -> Rows:
        old, new = _loaded_int(before, default), _loaded_int(after, default)
        old = 0 if old is None else old
        if new is not None and new <= old:
            return []
        return [_row(name, TRUST, name, str(after if new is None else new), str(old))]
    return guard
