
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.core.layouts import tree_v7 as tree_v7
from src.core.ui_preferences import TerminalLayoutEntry

TERMINAL_PREFIX = "terminal:"

PRIMARY_SLOT = "terminal:@primary"

ROW_SLOT_RE = re.compile(r"^terminal:row:(\d{1,15})$")

MIN_MEMBERS = 2


PAGE_TAB_RE = re.compile(r"^page:[0-9a-f]{16}$")

WIDGET_TAB_RE = re.compile(r"^widget:[a-z0-9][a-z0-9._-]{0,63}$")

PAGE_SLOT_PREFIX = "terminal:pg-"


class ShapeInvalid(ValueError):
    pass


class ShapeUnresolved(ValueError):

    def __init__(self, slots: List[str]) -> None:
        super().__init__("terminal slots that name no session row: " + ", ".join(slots))
        self.slots = slots


def row_slot(row_id: int) -> str:
    return f"{TERMINAL_PREFIX}row:{int(row_id)}"


def validate(shape: Any) -> Dict[str, Any]:
    try:
        entry = TerminalLayoutEntry.model_validate(shape)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise ShapeInvalid(str(first.get("msg") or "the shape is not a terminal layout")) from None
    return entry.model_dump(mode="json")


def _grid_terminal_slots(layout: Optional[Dict[str, Any]]) -> List[str]:
    if not layout:
        return []
    if tree_v7.is_v7(layout):
        return tree_v7.terminal_slots_of(layout)
    out: List[str] = []
    for row in layout.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for slot in row.get("slots") or []:
            sid = slot.get("id") if isinstance(slot, dict) else None
            if isinstance(sid, str) and sid.startswith(TERMINAL_PREFIX) and sid not in out:
                out.append(sid)
    return out


def _components(shape: Dict[str, Any]) -> List[str]:
    if shape.get("layout"):
        return _grid_terminal_slots(shape["layout"])
    return list(shape.get("groups") or {})


def _tabs_of(groups: Dict[str, Any], slot: str) -> List[str]:
    tabs = (groups.get(slot) or {}).get("tabs") or []
    return list(tabs) if tabs else [slot]


def displayed_terminals(shape: Dict[str, Any]) -> List[str]:
    groups = shape.get("groups") or {}
    components = _components(shape)
    seen: List[str] = []
    for component in components:
        for tab in _tabs_of(groups, component):
            if (
                tab not in seen
                and not PAGE_TAB_RE.match(tab)
                and not WIDGET_TAB_RE.match(tab)
                and not tab.startswith(PAGE_SLOT_PREFIX)
            ):
                seen.append(tab)
    return seen


def page_tab_ids(shape: Dict[str, Any]) -> List[str]:
    groups = shape.get("groups") or {}
    seen: List[str] = []
    for component in _components(shape):
        for tab in _tabs_of(groups, component):
            if PAGE_TAB_RE.match(tab) and tab not in seen:
                seen.append(tab)
    return seen


def has_enough_members(rows: List[int], shape: Dict[str, Any]) -> bool:
    return len(rows) >= MIN_MEMBERS or (len(rows) == 1 and bool(page_tab_ids(shape)))


def member_row_ids(shape: Dict[str, Any]) -> List[int]:
    rows: List[int] = []
    unresolved: List[str] = []
    for tab in displayed_terminals(shape):
        if tab == PRIMARY_SLOT:
            raise ShapeInvalid("a layout names its members by row; 'terminal:@primary' is not a member")
        match = ROW_SLOT_RE.match(tab)
        if match is None:
            unresolved.append(tab)
            continue
        rows.append(int(match.group(1)))
    if unresolved:
        raise ShapeUnresolved(unresolved)
    return list(dict.fromkeys(rows))


def with_member_added(shape: Dict[str, Any], row_id: int) -> Dict[str, Any]:
    slot = row_slot(row_id)
    if slot in displayed_terminals(shape):
        return shape
    out = copy.deepcopy(shape)
    groups = out.setdefault("groups", {})
    components = _components(out)
    if not components:
        raise ShapeInvalid("the layout shows no terminal to add a tab to")
    first = components[0]
    groups[first] = {"tabs": _tabs_of(groups, first) + [slot]}
    return out


def _drop_cell(layout: Dict[str, Any], slot: str) -> Dict[str, Any]:
    rows = layout.get("rows") or []
    for row in rows:
        held = row.get("reserved")
        if held:
            row["reserved"] = [r for r in held if r.get("of") != slot]
            if not row["reserved"]:
                row.pop("reserved")
    kept_rows = []
    for row in rows:
        slots = row.get("slots") or []
        at = next((i for i, s in enumerate(slots) if s.get("id") == slot), -1)
        if at >= 0:
            slots = [s for s in slots if s.get("id") != slot]
            if row.get("reserved"):
                row["reserved"] = [
                    dict(r, at=r["at"] - 1) if r.get("at", 0) > at else r for r in row["reserved"]
                ]
            total = sum(float(s.get("fr") or 0) for s in slots if float(s.get("fr") or 0) > 0)
            for s in slots:
                s["fr"] = (float(s["fr"]) / total) if total > 0 else 1 / len(slots)
            row["slots"] = slots
        if row.get("slots") or row.get("reserved"):
            kept_rows.append(row)
    flex = [r for r in kept_rows if r.get("kind") == "flex"]
    flex_total = sum(float(r.get("size") or 0) for r in flex)
    if flex and flex_total > 0 and len(flex) != len([r for r in rows if r.get("kind") == "flex"]):
        for r in flex:
            r["size"] = float(r["size"]) / flex_total
    layout["rows"] = kept_rows
    for key in ("hidden", "collapsed", "headerOff"):
        if isinstance(layout.get(key), list):
            layout[key] = [s for s in layout[key] if s != slot]
    return layout


def _drop_slot(layout: Dict[str, Any], slot: str) -> Optional[Dict[str, Any]]:
    if tree_v7.is_v7(layout):
        return tree_v7.without_slot(layout, slot)
    dropped = _drop_cell(layout, slot)
    return dropped if dropped.get("rows") else None


def with_member_removed(shape: Dict[str, Any], row_id: int) -> Tuple[Dict[str, Any], bool]:
    slot = row_slot(row_id)
    if slot not in displayed_terminals(shape):
        return shape, False
    out = copy.deepcopy(shape)
    groups = out.setdefault("groups", {})
    components = _components(out)
    for component in components:
        tabs = _tabs_of(groups, component)
        if slot not in tabs:
            continue
        rest = [t for t in tabs if t != slot]
        if rest:
            groups[component] = {"tabs": rest}
            continue
        groups.pop(component, None)
        if out.get("layout"):
            out["layout"] = _drop_slot(out["layout"], component)
    return out, True
