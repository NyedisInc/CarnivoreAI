
from __future__ import annotations

from typing import Any, Dict, List, Mapping

DEFAULT_KEY = "default"
"""The wrapper flag launch reads first."""


def _rows(value: Any) -> List[Dict[str, Any]]:
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def merge_wrappers(existing: Any, incoming: Any) -> List[Dict[str, Any]]:
    out = _rows(existing)
    position: Dict[Any, int] = {}
    for index, row in enumerate(out):
        position.setdefault(row.get("id"), index)
    for row in _rows(incoming):
        index = position.get(row.get("id"))
        if index is None:
            row[DEFAULT_KEY] = False
            position[row.get("id")] = len(out)
            out.append(row)
            continue
        local = out[index]
        if DEFAULT_KEY in local or DEFAULT_KEY in row:
            row[DEFAULT_KEY] = bool(local.get(DEFAULT_KEY, False))
        out[index] = row
    return out
