
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from src.cplugs.huddle import rules
from src.cplugs.huddle.rules import TaskManagerInvalid, TaskManagerNotFound

FIELD = "review_checks"
MAX_CHECKS = 30
MAX_LABEL = 300


def build(labels: object) -> Dict[str, Optional[str]]:
    if labels is None:
        return {}
    if not isinstance(labels, (list, tuple)):
        raise TaskManagerInvalid(f"{FIELD} is a list of short labels")
    if len(labels) > MAX_CHECKS:
        raise TaskManagerInvalid(f"{FIELD} holds at most {MAX_CHECKS} checks")
    checks = [{"id": f"c{n}", "label": " ".join(rules.clean_text(label, "review check", MAX_LABEL).split()),
               "checked": False, "checked_at": None, "checked_by": None} for n, label in enumerate(labels, 1)]
    return {FIELD: json.dumps(checks) if checks else None}


def parse(raw: object) -> List[Dict[str, Any]]:
    if not isinstance(raw, str) or not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def wire(row: Any) -> Dict[str, List[Dict[str, Any]]]:
    return {FIELD: parse(row[FIELD])}


def unticked(checks: Sequence[Dict[str, Any]]) -> int:
    return sum(1 for check in checks if not check.get("checked"))


def tick(raw: object, check_id: str, checked: bool, by: str, now: float) -> str:
    checks = parse(raw)
    for check in checks:
        if check.get("id") == check_id:
            check.update(checked=checked, checked_at=now if checked else None, checked_by=by if checked else None)
            return json.dumps(checks)
    raise TaskManagerNotFound(f"this item has no review check {check_id}")
