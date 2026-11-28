
from __future__ import annotations

from typing import Any, Dict, Iterable

KIND = "withhold"
MAX_IDS, MAX_ID = 64, 64


def build(ids: Iterable[str]) -> Dict[str, Any]:
    clean = sorted({i for i in ids if isinstance(i, str) and 0 < len(i) <= MAX_ID and i.isprintable()})
    return {"ids": clean[:MAX_IDS]}


def valid(v: Any) -> bool:
    if not isinstance(v, dict) or set(v) != {"ids"} or not isinstance(v["ids"], list):
        return False
    ids = v["ids"]
    return (len(ids) <= MAX_IDS and all(isinstance(i, str) and 0 < len(i) <= MAX_ID and i.isprintable() for i in ids)
            and ids == sorted(set(ids)))
