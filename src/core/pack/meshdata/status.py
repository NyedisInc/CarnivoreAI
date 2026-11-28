
from __future__ import annotations

from typing import Any, Iterable, Dict

from src.core.pack.meshdata.hlc import MAX_MS

KIND = "status"
MAX_LABEL, MAX_VERSION, MAX_LINKS, MAX_ID = 80, 32, 64, 64
_KEYS = frozenset({"label", "app_version", "links", "up_since"})


def build(label: str, app_version: str, link_ids: Iterable[str], up_since_ms: int) -> Dict[str, Any]:
    ids = sorted({i for i in link_ids if isinstance(i, str) and 0 < len(i) <= MAX_ID})[:MAX_LINKS]
    return {"label": str(label)[:MAX_LABEL], "app_version": str(app_version)[:MAX_VERSION], "links": ids,
            "up_since": max(0, min(int(up_since_ms), MAX_MS))}


def valid(v: Any) -> bool:
    if not isinstance(v, dict) or set(v) != _KEYS:
        return False
    links = v["links"]
    return (isinstance(v["label"], str) and len(v["label"]) <= MAX_LABEL
            and isinstance(v["app_version"], str) and len(v["app_version"]) <= MAX_VERSION
            and isinstance(links, list) and len(links) <= MAX_LINKS
            and all(isinstance(i, str) and 0 < len(i) <= MAX_ID for i in links)
            and isinstance(v["up_since"], int) and not isinstance(v["up_since"], bool) and 0 <= v["up_since"] <= MAX_MS)
