
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.core.session_status import STATUS_DEAD

AGENT_FAMILIES = ("claude", "codex")


def is_agent_row(info: Any) -> bool:
    family = (getattr(info, "agent_family", None) or "").lower()
    if family:
        return family in AGENT_FAMILIES
    agent = (getattr(info, "agent_type", None) or getattr(info.session, "agent_type", None) or "").lower()
    return agent.startswith(AGENT_FAMILIES)


def can_take(info: Any) -> bool:
    return getattr(info, "activity_status", None) != STATUS_DEAD


def running_agents(infos: Iterable[Any], project_id: int) -> List[Any]:
    return [i for i in infos if getattr(i, "project_id", None) == project_id and is_agent_row(i) and can_take(i)]


def _activity_stamp(info: Any) -> float:
    stamp = getattr(info.session, "last_activity", None)
    return stamp.timestamp() if hasattr(stamp, "timestamp") else 0.0


def running_lead(own: List[Any], keys: Mapping[str, str], lead_key: str) -> Optional[str]:
    return next((i.session.id for i in own if lead_key and keys.get(i.session.id) == lead_key), None)


def most_recent(own: List[Any]) -> Optional[str]:
    return max(own, key=_activity_stamp).session.id if own else None


def pick_sleeper(asleep: Iterable[Mapping[str, Any]], project_id: int, lead_key: str) -> Optional[str]:
    own: List[Dict[str, Any]] = [dict(s) for s in asleep if str(s.get("project_id")) == str(project_id)]
    if lead_key and any(s["session_uuid"] == lead_key for s in own):
        return lead_key
    return own[0]["session_uuid"] if own else None
