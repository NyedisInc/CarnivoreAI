
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_FIELDS: Mapping[str, Mapping[str, Any]] = json.loads((Path(__file__).parents[1] / "cplug.json").read_text(encoding="utf-8"))["settings_schema"]["fields"]

ENABLED = "nudgeEnabled"
MINUTES, TRIES, MAX_ITEMS = "nudgeMinutes", "nudgeTries", "nudgeMaxItems"
UNCLAIMED_TEXT, PICKUP_TEXT, CLAIMED_TEXT = "unclaimedText", "pickupText", "claimedText"
TEXT_KEYS = (UNCLAIMED_TEXT, PICKUP_TEXT, CLAIMED_TEXT)


def default(key: str) -> Any:
    return _FIELDS[key]["default"]


def clamp_number(key: str, value: Any) -> float:
    field = _FIELDS[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(field["default"])
    return float(min(max(value, field["min"]), field["max"]))


def text_or_default(key: str, value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else _FIELDS[key]["default"]


@dataclass(frozen=True)
class Settings:

    enabled: bool
    minutes: float
    tries: int
    max_items: int
    texts: Mapping[str, str]


def read(values: Mapping[str, Any]) -> Settings:
    return Settings(enabled=values.get(ENABLED) is True, minutes=clamp_number(MINUTES, values.get(MINUTES)), tries=int(clamp_number(TRIES, values.get(TRIES))),
                    max_items=int(clamp_number(MAX_ITEMS, values.get(MAX_ITEMS))),
                    texts={k: text_or_default(k, values.get(k)) for k in TEXT_KEYS})
