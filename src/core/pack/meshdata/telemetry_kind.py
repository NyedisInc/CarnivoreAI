
from __future__ import annotations

import json
import math
from typing import Any, FrozenSet, Mapping, Optional

from src.core.computers import direction
from src.core.pack.meshdata import workspace_kind

KIND = "telemetry"
CAP = 64
TTL_SECONDS = 90.0
REFRESH_SECONDS = 10.0
MAX_VALUE_BYTES = 4096

MAX_LABEL = 64
MAX_VERSION = 32
MAX_FEED_BUCKETS = 15
MAX_ACTIVE_MODELS = 16
MAX_HOT = 5
MAX_AGENTS = 10
MAX_LEDGER = 8
MAX_STR = 128
MAX_EPOCH = 1e11
MAX_COUNT = 10**13
MAX_RATE = 1e12

_TOP_KEYS: FrozenSet[str] = frozenset({
    "ts",
    "label",
    "app_version",
    "vitals_15m",
    "hot_15m",
    "agents_5m",
    "machine",
    "ledger",
})

_VITALS_NUMERIC_KEYS: FrozenSet[str] = frozenset({
    "tpm_5m",
    "tpm_15m",
    "tpm_60m",
    "usd_hr_5m",
    "usd_hr_15m",
    "usd_hr_60m",
    "cache_read_15m",
    "cache_denom_15m",
})

_VITALS_KEYS: FrozenSet[str] = _VITALS_NUMERIC_KEYS | frozenset({
    "active_models_15m",
    "model_tokens_15m",
    "feed_rate",
    "feed_buckets_1m",
})

_FEED_RATE_KEYS: FrozenSet[str] = frozenset({
    "span_seconds",
    "fresh",
    "cache_write",
    "cache_read",
    "out",
})

_HOT_KEYS: FrozenSet[str] = frozenset({
    "conversation_id",
    "provider",
    "project",
    "model",
    "tokens",
    "cost_nano",
})

_AGENT_KEYS: FrozenSet[str] = frozenset({
    "conversation_id",
    "name",
    "tokens",
    "tokens_per_minute",
})

_MACHINE_FLOAT_KEYS: FrozenSet[str] = frozenset({
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "load_1",
    "load_5",
    "load_15",
})

_MACHINE_INT_KEYS: FrozenSet[str] = frozenset({
    "cpu_count",
    "memory_used_bytes",
    "memory_total_bytes",
    "disk_free_bytes",
    "disk_total_bytes",
    "uptime_seconds",
    "live_agents",
})

_MACHINE_KEYS: FrozenSet[str] = _MACHINE_FLOAT_KEYS | _MACHINE_INT_KEYS

_LEDGER_KEYS: FrozenSet[str] = frozenset({
    "account_key",
    "id",
    "name",
    "provider",
    "plan",
    "five_hour_pct",
    "seven_day_pct",
    "five_hour_resets_at",
    "seven_day_resets_at",
    "credential_state",
    "spend_usd",
})

_PROVIDERS: FrozenSet[str] = frozenset({"claude", "codex", "antigravity"})
_CREDENTIAL_STATES: FrozenSet[str] = frozenset({
    "ok",
    "expired",
    "missing",
    "refused",
    "rate_limited",
    "error",
    "unknown",
})

_SAFE_SCHEMA_KEYS: FrozenSet[str] = frozenset({
    "tokens",
    "tokens_per_minute",
    "model_tokens_15m",
    "credential_state",
})


def _is_finite_num(value: Any, *, lo: float = 0.0, hi: float = MAX_RATE) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and lo <= float(value) <= hi
    )


def _is_strict_int(value: Any, *, lo: int = 0, hi: int = MAX_COUNT) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def _is_safe_str(value: Any, limit: int, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    if not allow_empty and not value:
        return False
    return len(value) <= limit and "/" not in value and "\\" not in value and value.isprintable()


def _has_forbidden_key(obj: Any, depth: int = 0) -> bool:
    if depth > 6:
        return True
    if isinstance(obj, Mapping):
        for key, val in obj.items():
            if not isinstance(key, str) or (key not in _SAFE_SCHEMA_KEYS and workspace_kind.is_secret_field(key)):
                return True
            if _has_forbidden_key(val, depth + 1):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_forbidden_key(item, depth + 1):
                return True
    return False


def _valid_feed_rate(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or not set(value) <= _FEED_RATE_KEYS:
        return False
    for key in _FEED_RATE_KEYS:
        if key not in value:
            return False
        hi = 1e6 if key == "span_seconds" else MAX_RATE
        if not _is_finite_num(value[key], lo=0.0, hi=hi):
            return False
    return True


def _valid_feed_buckets(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > MAX_FEED_BUCKETS:
        return False
    for bucket in value:
        if not isinstance(bucket, (list, tuple)) or len(bucket) != 5:
            return False
        if not all(_is_strict_int(n, lo=0, hi=MAX_COUNT) for n in bucket):
            return False
    return True


def _valid_vitals(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value) <= _VITALS_KEYS:
        return False
    for key in _VITALS_NUMERIC_KEYS:
        if key in value and value[key] is not None and not _is_finite_num(value[key], lo=0.0, hi=MAX_RATE):
            return False
    if "active_models_15m" in value:
        models = value["active_models_15m"]
        if not isinstance(models, list) or len(models) > MAX_ACTIVE_MODELS:
            return False
        if not all(_is_safe_str(m, 96) for m in models):
            return False
    if "model_tokens_15m" in value:
        mt = value["model_tokens_15m"]
        if not isinstance(mt, dict) or len(mt) > MAX_ACTIVE_MODELS:
            return False
        if not all(_is_safe_str(k, 96) and _is_strict_int(v, lo=0, hi=MAX_COUNT) for k, v in mt.items()):
            return False
    if "feed_rate" in value and not _valid_feed_rate(value["feed_rate"]):
        return False
    if "feed_buckets_1m" in value and not _valid_feed_buckets(value["feed_buckets_1m"]):
        return False
    return True


def _valid_hot(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > MAX_HOT:
        return False
    for item in value:
        if not isinstance(item, dict) or not set(item) <= _HOT_KEYS:
            return False
        if not _is_safe_str(item.get("conversation_id"), MAX_STR):
            return False
        if not _is_safe_str(item.get("provider"), 32):
            return False
        if item.get("project") is not None and not _is_safe_str(item.get("project"), MAX_STR, allow_empty=True):
            return False
        if item.get("model") is not None and not _is_safe_str(item.get("model"), 96, allow_empty=True):
            return False
        if not _is_strict_int(item.get("tokens"), lo=0, hi=MAX_COUNT):
            return False
        if item.get("cost_nano") is not None and not _is_strict_int(item.get("cost_nano"), lo=0, hi=MAX_COUNT * 1000):
            return False
    return True


def _valid_agents(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > MAX_AGENTS:
        return False
    for item in value:
        if not isinstance(item, dict) or not set(item) <= _AGENT_KEYS:
            return False
        if not _is_safe_str(item.get("conversation_id"), MAX_STR):
            return False
        if not _is_safe_str(item.get("name"), 96, allow_empty=True):
            return False
        if not _is_strict_int(item.get("tokens"), lo=0, hi=MAX_COUNT):
            return False
        if not _is_finite_num(item.get("tokens_per_minute"), lo=0.0, hi=MAX_RATE):
            return False
    return True


def _valid_machine(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value) <= _MACHINE_KEYS:
        return False
    for key in _MACHINE_FLOAT_KEYS:
        if key in value and value[key] is not None:
            hi = 100.5 if key.endswith("_percent") else 1e6
            if not _is_finite_num(value[key], lo=0.0, hi=hi):
                return False
    for key in _MACHINE_INT_KEYS:
        if key in value and value[key] is not None:
            if not _is_strict_int(value[key], lo=0, hi=10**16):
                return False
    return True


def _valid_reset_stamp(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return _is_safe_str(value, 64)
    return _is_finite_num(value, lo=0.0, hi=MAX_EPOCH)


def _valid_ledger(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > MAX_LEDGER:
        return False
    for item in value:
        if not isinstance(item, dict) or not set(item) <= _LEDGER_KEYS:
            return False
        if item.get("provider") not in _PROVIDERS:
            return False
        for key, limit in (("account_key", MAX_STR), ("id", 64), ("name", 96), ("plan", 64)):
            if item.get(key) is not None and not _is_safe_str(item[key], limit, allow_empty=True):
                return False
        for pct_key in ("five_hour_pct", "seven_day_pct"):
            if item.get(pct_key) is not None and not _is_finite_num(item[pct_key], lo=0.0, hi=100.0):
                return False
        for reset_key in ("five_hour_resets_at", "seven_day_resets_at"):
            if not _valid_reset_stamp(item.get(reset_key)):
                return False
        cred = item.get("credential_state")
        if cred is not None and cred not in _CREDENTIAL_STATES:
            return False
        if item.get("spend_usd") is not None and not _is_finite_num(item["spend_usd"], lo=0.0, hi=1e9):
            return False
    return True


def valid(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value) <= _TOP_KEYS or "ts" not in value:
        return False
    if _has_forbidden_key(value):
        return False
    if not _is_finite_num(value["ts"], lo=1e-9, hi=MAX_EPOCH):
        return False
    if "label" in value and not _is_safe_str(value["label"], MAX_LABEL, allow_empty=True):
        return False
    if "app_version" in value and not _is_safe_str(value["app_version"], MAX_VERSION, allow_empty=True):
        return False
    if "vitals_15m" in value and not _valid_vitals(value["vitals_15m"]):
        return False
    if "hot_15m" in value and not _valid_hot(value["hot_15m"]):
        return False
    if "agents_5m" in value and not _valid_agents(value["agents_5m"]):
        return False
    if "machine" in value and not _valid_machine(value["machine"]):
        return False
    if "ledger" in value and not _valid_ledger(value["ledger"]):
        return False
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return False
    return len(text) <= MAX_VALUE_BYTES


def approved_listed(lst: Any, iid: Optional[str]) -> bool:
    entry = lst.entry(iid) if iid is not None and hasattr(lst, "entry") else None
    return entry is not None and not entry.one_way


def approved(lst: Any, iid: Optional[str]) -> bool:
    return approved_listed(lst, iid) and not direction.contained(iid)


def origin_ok(lst: Any, origin: Optional[str]) -> bool:
    return approved_listed(lst, origin)


def serve_ok(lst: Any, peer: Optional[str]) -> bool:
    return approved(lst, peer)
