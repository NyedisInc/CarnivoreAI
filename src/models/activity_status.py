from __future__ import annotations

from typing import Literal, Optional, Protocol, get_args

ActivityStatus = Literal[
    "working", "working_subagent", "question", "notice", "finished_unread", "idle", "dead", "unknown",
]

ACTIVITY_STATUSES: frozenset[str] = frozenset(get_args(ActivityStatus))

RESTING: frozenset[str] = frozenset({"idle", "finished_unread"})

BUSY: frozenset[str] = frozenset({"working", "working_subagent"})

BLOCKED_ON_OWNER: frozenset[str] = frozenset({"question"})

ASKING: frozenset[str] = frozenset({"question", "notice"})

TURN_OVER: frozenset[str] = RESTING | ASKING


def known_or_unknown(value: object) -> object:
    if isinstance(value, str) and value not in ACTIVITY_STATUSES:
        return "unknown"
    return value


class _HasActivity(Protocol):

    activity_status: str
    startup_gate: Optional[str]


def blocked_on_owner(info: _HasActivity) -> bool:
    return info.activity_status in BLOCKED_ON_OWNER or info.startup_gate != "ready"
