
from __future__ import annotations

import json
from typing import Any, Dict, List


from src.core.layouts import tree_v7 as layout_tree_v7
from src.core.ui_preferences.constants import MAX_LAYOUT_BYTES


def check_grid(value: Dict[str, Any], what: str, *, allow_tree: bool = False) -> Dict[str, Any]:
    version = value.get("v")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError(f"a {what} carries an integer 'v'")
    json_size_cap(value, MAX_LAYOUT_BYTES, f"a {what} is too large to store")
    if allow_tree and layout_tree_v7.is_v7(value):
        try:
            layout_tree_v7.check_layout(value)
        except layout_tree_v7.TreeInvalid as exc:
            raise ValueError(f"a v7 {what} is not a split tree: {exc}") from None
        return value
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"a {what} carries a non-empty 'rows' list")
    return value


def json_size_cap(value: Any, limit: int, message: str) -> None:
    if len(json.dumps(value).encode("utf-8")) > limit:
        raise ValueError(message)


def unique_placements(items: List[Any], where: str) -> None:
    seen = set()
    for item in items:
        key = (item.widget, item.target, item.instance)
        if key in seen:
            raise ValueError(f"a widget (or a family copy's target) appears in {where} once per copy id")
        seen.add(key)
