
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

AI_CAPABILITIES = ("chat", "embed")
MAX_CALLS_PER_DAY = 1000
MAX_TOKENS_PER_DAY = 1_000_000
PERMISSION_PREFIX = "ai_features:"
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_FIELDS = frozenset({"capability", "calls_per_day", "tokens_per_day"})


class AiFeatureError(ValueError):
    pass


@dataclass(frozen=True)
class AiFeature:

    name: str
    capability: str
    calls_per_day: int
    tokens_per_day: int


def feature_id(cplug_id: str, name: str) -> str:
    return f"cplug.{cplug_id}.{name}"


def permission_name(cplug_id: str, name: str) -> str:
    return PERMISSION_PREFIX + feature_id(cplug_id, name)


def _bounded(value: Any, ceiling: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= ceiling


def parse_ai_features(cplug_id: str, raw: Any, permissions: Tuple[str, ...]) -> Dict[str, AiFeature]:
    where = f"{cplug_id}: ai_features"
    if not isinstance(raw, dict):
        raise AiFeatureError(f"{where} must be an object of feature name to declaration")
    out: Dict[str, AiFeature] = {}
    for name, block in raw.items():
        if not isinstance(name, str) or not _NAME.match(name):
            raise AiFeatureError(f"{where}: {name!r} must match {_NAME.pattern}")
        if not isinstance(block, dict) or set(block) != _FIELDS:
            raise AiFeatureError(f"{where}.{name} must hold exactly {sorted(_FIELDS)}")
        capability = block["capability"]
        if capability not in AI_CAPABILITIES:
            raise AiFeatureError(f"{where}.{name}: capability {capability!r} is not one of {AI_CAPABILITIES} (never agent)")
        if not _bounded(block["calls_per_day"], MAX_CALLS_PER_DAY):
            raise AiFeatureError(f"{where}.{name}: calls_per_day must be an integer from 1 to {MAX_CALLS_PER_DAY}")
        if not _bounded(block["tokens_per_day"], MAX_TOKENS_PER_DAY):
            raise AiFeatureError(f"{where}.{name}: tokens_per_day must be an integer from 1 to {MAX_TOKENS_PER_DAY}")
        out[name] = AiFeature(name, capability, block["calls_per_day"], block["tokens_per_day"])
    asked = {p for p in permissions if p.startswith(PERMISSION_PREFIX)}
    declared = {permission_name(cplug_id, n) for n in out}
    if asked != declared:
        raise AiFeatureError(f"{where}: the {PERMISSION_PREFIX}<feature id> permissions {sorted(asked)} must match the "
                             f"declared features {sorted(declared)}")
    return out
