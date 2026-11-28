
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple


class SessionChainsUnreadable(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionFacts:

    session_uuid: str
    title: Optional[str]
    project_id: Optional[int]
    host_key: str
    lifecycle: str
    lifecycle_source: Optional[str]
    archived: bool
    asleep: bool
    claude_session_uuid: Optional[str]
    last_active_epoch: Optional[float]
    working_dir: Optional[str] = None


@dataclass(frozen=True)
class ChainSnapshot:

    sessions: Tuple[SessionFacts, ...]
    conversation_parents: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    session_parents: Dict[str, FrozenSet[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class RunningScan:

    conversations: FrozenSet[str]
    unreadable: int


def read_snapshot() -> ChainSnapshot:
    from src.plugins.host import session_chains  # noqa: PLC0415

    return session_chains.read_snapshot()


def read_running() -> RunningScan:
    from src.plugins.host import session_chains  # noqa: PLC0415

    return session_chains.read_running()
