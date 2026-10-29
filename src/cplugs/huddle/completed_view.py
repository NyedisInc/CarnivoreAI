
from __future__ import annotations

from typing import Any, Dict, List

from . import rules

KEEP = ("id", "list", "state", "status", "section", "group", "position", "revision", "kind", "number")


def is_completed(item: Dict[str, Any]) -> bool:
    return item.get("state") in rules.APPROVED_STATES


def placeholder(item: Dict[str, Any]) -> Dict[str, Any]:
    return {**{k: item.get(k) for k in KEEP}, "text": "", "note": "", "thread": [], "deleted": False, "placeholder": True}


def apply_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [placeholder(i) if is_completed(i) else i for i in items]


def apply_body(body: Dict[str, Any]) -> Dict[str, Any]:
    return {**body, "items": apply_items(body["items"])}


def apply_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**g, "items": apply_items(g["items"])} for g in groups]
