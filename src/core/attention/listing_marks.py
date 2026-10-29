
from __future__ import annotations

from typing import Any, Optional

from src.core.attention.background_claims import standing_background_claims
from src.core.attention.evidence import FAMILY_CODEX
from src.core.attention.workflow_activity import workflow_active


def marks_stamp(evidence: Any) -> tuple:
    from src.core.auto_sleep.live_work import hold_for
    from src.core.sessions.agent_update import agent_update_status, version_text

    hold = hold_for(evidence, require_measured=False)
    registry = getattr(evidence, "registry", None)
    update: Optional[Any] = None
    if getattr(evidence, "agent_family", None) != FAMILY_CODEX and getattr(registry, "known", False):
        update = agent_update_status(pid=getattr(registry, "pid", None),
                                     registry_version=version_text(getattr(registry, "version", None)))
    subagents, timers, skills = (getattr(evidence, name, None) for name in ("subagents", "timers", "skills"))
    parked = getattr(evidence, "parked_work", None)
    return (
        _fields(subagents, "state", "running", "total"),
        _fields(timers, "state", "live", "next_fire_at"),
        _fields(skills, "state", "fired", "last_skill", "last_at"),
        (getattr(parked, "is_live", False), (getattr(parked, "entries", None) or (None,))[0]),
        standing_background_claims(evidence), getattr(evidence, "background_open", None),
        workflow_active(evidence),
        getattr(getattr(evidence, "transcript", None), "mcp_events", ()),
        (hold.reasons, hold.text) if hold else None, update,
    )


def _fields(value: Any, *names: str) -> Optional[tuple]:
    return None if value is None else tuple(getattr(value, name, None) for name in names)
