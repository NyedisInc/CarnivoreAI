
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional

from src.core.automations import models as m

NONE, OK, WARNING, ERROR, DISABLED = "none", "ok", "warning", "error", "disabled"
_WARNING_RUNS = (m.SKIPPED, m.CANCELLED, m.WAITING)
_SEVERITY = (ERROR, WARNING, OK)


@dataclass(frozen=True)
class TimerStatus:

    state: str
    total: int
    enabled: int


def automation_state(automation: Mapping[str, Any], run: Optional[Mapping[str, Any]]) -> str:
    status = run.get("status") if run else None
    if status == m.FAILED:
        return WARNING if automation.get("retry_due_at") is not None else ERROR
    return WARNING if status in _WARNING_RUNS else OK


def roll_up(items: Iterable["tuple[Mapping[str, Any], Optional[Mapping[str, Any]]]"]) -> TimerStatus:
    total = enabled = 0
    seen = set()
    for automation, run in items:
        total += 1
        if not automation.get("enabled"):
            continue
        enabled += 1
        seen.add(automation_state(automation, run))
    if total == 0:
        return TimerStatus(NONE, 0, 0)
    if enabled == 0:
        return TimerStatus(DISABLED, total, 0)
    return TimerStatus(next(word for word in _SEVERITY if word in seen), total, enabled)


def session_uuid_of(automation: Mapping[str, Any]) -> str:
    target = automation.get("target") or {}
    return str(target.get("session_uuid") or "") if target.get("kind") == "session_message" else ""


def pairs_by_session(automations: Iterable[Mapping[str, Any]], runs: Mapping[str, Mapping[str, Any]]) -> Dict[str, list]:
    grouped: Dict[str, list] = {}
    for automation in automations:
        uuid = session_uuid_of(automation)
        if uuid:
            grouped.setdefault(uuid, []).append((automation, runs.get(automation["automation_id"])))
    return grouped


def by_session(automations: Iterable[Mapping[str, Any]], runs: Mapping[str, Mapping[str, Any]]) -> Dict[str, TimerStatus]:
    return {uuid: roll_up(pairs) for uuid, pairs in pairs_by_session(automations, runs).items()}


def pair_of_schedule(entry: Mapping[str, Any]) -> "tuple[Dict[str, Any], Optional[Dict[str, Any]]]":
    retry = entry.get("next_fire_at") if entry.get("retrying") else None
    return ({"enabled": bool(entry.get("enabled")), "retry_due_at": retry},
            {"status": m.FAILED} if entry.get("failed") else None)


def overall(automations: Iterable[Mapping[str, Any]], runs: Mapping[str, Mapping[str, Any]]) -> TimerStatus:
    return roll_up((a, runs.get(a["automation_id"])) for a in automations)
