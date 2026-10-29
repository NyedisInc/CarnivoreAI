
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from src.core.session_agent_infer import restart_agent_type

WAKE_WRAPPER_NEEDED: str = "wrapper_needed"


def recorded_wake_agent(
    row: Mapping[str, Any], configured_ids: Optional[Iterable[str]]
) -> Optional[str]:
    usable = restart_agent_type(row.get("agent_type"), row.get("agent_family_source"))
    value = (usable or "").strip()
    if not value:
        return None
    if configured_ids is None:
        return value
    return value if value in set(configured_ids) else None


def wrapper_needed_detail(row: Mapping[str, Any], configured_ids: Iterable[str]) -> str:
    ids = list(configured_ids)
    recorded = (row.get("agent_type") or "").strip()
    inferred = recorded and restart_agent_type(recorded, row.get("agent_family_source")) is None
    if not recorded:
        why = "this session has no recorded wrapper"
    elif inferred:
        why = f"'{recorded}' was inferred from the pane, not chosen, so it is not launched unasked"
    else:
        why = f"'{recorded}' is not a configured launch wrapper"
    have = ", ".join(ids) if ids else "none"
    return f"{why}. pick a wrapper to wake it with; this install has {have}"
