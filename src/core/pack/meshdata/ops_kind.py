
from __future__ import annotations

from typing import Any, Optional

from src.core.computers import direction

KIND = "ops"
KEYS = ("placement_mode", "auto_distribute", "placement_model")
_MODES = ("stats", "enhanced")


def valid_shape(v: Any) -> bool:
    if v is None or isinstance(v, (bool, str)):
        return True
    return isinstance(v, dict) and set(v) == {"connection", "model"}


def valid(key: str, v: Any) -> bool:
    if key == "placement_mode":
        return isinstance(v, str) and v in _MODES
    if key == "auto_distribute":
        return isinstance(v, bool)
    if key == "placement_model":
        if v is None:
            return True
        return (isinstance(v, dict) and set(v) == {"connection", "model"} and isinstance(v["connection"], str) and 1 <= len(v["connection"]) <= 120
                and isinstance(v["model"], str) and 1 <= len(v["model"]) <= 200)
    return False


def origin_ok(lst: Any, origin: Optional[str]) -> bool:
    entry = lst.entry(origin) if origin is not None and hasattr(lst, "entry") else None
    return entry is not None and not entry.one_way


def serve_ok(lst: Any, peer: Optional[str]) -> bool:
    return origin_ok(lst, peer) and not direction.contained(peer)
