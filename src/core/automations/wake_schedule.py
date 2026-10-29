
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.core.automations import timer_status


def next_due(automation: Mapping[str, Any]) -> Optional[float]:
    due = [t for t in (automation.get("next_fire_at"), automation.get("retry_due_at")) if t]
    return float(min(due)) if due else None


def waking_by_session(automations: Iterable[Mapping[str, Any]], asleep_uuids: Iterable[str]) -> Dict[str, List[Mapping[str, Any]]]:
    asleep = set(asleep_uuids)
    out: Dict[str, List[Mapping[str, Any]]] = {}
    for automation in automations:
        uuid = timer_status.session_uuid_of(automation)
        if not uuid or uuid not in asleep or not automation.get("enabled"):
            continue
        if (automation.get("target") or {}).get("if_asleep", "wake") != "wake":
            continue
        if next_due(automation) is not None:
            out.setdefault(uuid, []).append(automation)
    for listed in out.values():
        listed.sort(key=lambda a: next_due(a) or 0.0)
    return out


def waking_automations(automations: Iterable[Mapping[str, Any]], asleep_uuids: Iterable[str]) -> Dict[str, float]:
    return {uuid: next_due(listed[0]) for uuid, listed in waking_by_session(automations, asleep_uuids).items()}
