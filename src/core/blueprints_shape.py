
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Mapping, Optional

from src.core.layouts import shape as shape_rules

MEMBER_SLOT_PREFIX = "terminal:member:"

_MEMBER_SLOT_RE = re.compile(r"^terminal:member:(\d{1,2})$")

DEFAULT_COLUMNS = 3

_PLACEHOLDER_BASE = 900_000_000_000_000


def member_slot(index: int) -> str:
    return f"{MEMBER_SLOT_PREFIX}{int(index)}"


def check_template(template: Any, member_count: int) -> Dict[str, Any]:
    try:
        canonical = shape_rules.validate(template)
    except shape_rules.ShapeInvalid as exc:
        raise ValueError(f"shape_template: {exc}") from None
    for slot in shape_rules.displayed_terminals(canonical):
        match = _MEMBER_SLOT_RE.match(slot)
        if match is None:
            raise ValueError(
                f"shape_template: {slot!r} is not a member slot ('terminal:member:<index>')")
        if int(match.group(1)) >= member_count:
            raise ValueError(f"shape_template: {slot!r} names no session")
    return canonical


def _rename(value: Any, renames: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return renames.get(value, value)
    if isinstance(value, list):
        return [_rename(v, renames) for v in value]
    if isinstance(value, dict):
        return {renames.get(k, k): _rename(v, renames) for k, v in value.items()}
    return value


def default_shape(row_ids: List[int]) -> Dict[str, Any]:
    chunks = [row_ids[i:i + DEFAULT_COLUMNS] for i in range(0, len(row_ids), DEFAULT_COLUMNS)]
    rows = []
    for n, chunk in enumerate(chunks, start=1):
        rows.append({
            "id": f"r{n}", "kind": "flex", "size": 1 / len(chunks),
            "slots": [{"id": shape_rules.row_slot(r), "fr": 1 / len(chunk)} for r in chunk],
        })
    layout = {"v": 6, "rows": rows, "hidden": [], "heroCollapsed": False, "collapsed": []}
    return {"layout": layout, "groups": {}}


def materialize(template: Optional[Dict[str, Any]], launched: Mapping[int, int],
                member_count: int) -> Dict[str, Any]:
    ordered = [launched[i] for i in sorted(launched)]
    if template is None:
        return default_shape(ordered)
    renames = {member_slot(i): shape_rules.row_slot(r) for i, r in launched.items()}
    missing = [i for i in range(member_count) if i not in launched]
    for i in missing:
        renames[member_slot(i)] = shape_rules.row_slot(_PLACEHOLDER_BASE + i)
    shape = _rename(copy.deepcopy(template), renames)
    for i in missing:
        shape, _ = shape_rules.with_member_removed(shape, _PLACEHOLDER_BASE + i)
    shown = set(shape_rules.displayed_terminals(shape))
    if not shown:
        return default_shape(ordered)
    for row_id in ordered:
        if shape_rules.row_slot(row_id) not in shown:
            shape = shape_rules.with_member_added(shape, row_id)
    return shape


def template_from_layout(shape: Dict[str, Any], member_row_ids: List[int]) -> Dict[str, Any]:
    renames = {shape_rules.row_slot(r): member_slot(i) for i, r in enumerate(member_row_ids)}
    return _rename(copy.deepcopy(shape), renames)
