
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.plugins.save.offload import constants as C
from src.plugins.save.offload import icloud
from src.plugins.save.offload.eligibility import ConversationVerdict, Evaluator, SessionVerdict
from src.plugins.sdk.session_chains import RunningScan


class ReportError(ValueError):
    pass



@dataclass(frozen=True)
class Readiness:

    ready: bool
    blockers: Tuple[str, ...]


@dataclass(frozen=True)
class Totals:

    sessions: int
    conversations: int
    bytes: int


@dataclass(frozen=True)
class Page:

    readiness: Readiness
    idle_days: int
    offloadable: Totals
    offloadable_any_idle: Totals
    no_session: Totals
    blocked: Dict[str, int]
    candidates: List[SessionVerdict]
    next_cursor: Optional[str]
    total_candidates: int


def readiness(roots: Sequence[Path], running: RunningScan, holding: Optional[Path] = None, icloud_root: Optional[Path] = None) -> Readiness:
    found = icloud.blockers([*roots, *([holding] if holding is not None else [])], icloud_root)
    if running.unreadable:
        found.append(C.BLOCKER_REGISTRY_UNREADABLE)
    return Readiness(not found, tuple(sorted(found)))


def _totals(sessions: int, conversations: Dict[str, ConversationVerdict]) -> Totals:
    return Totals(sessions, len(conversations), sum(v.bytes for v in conversations.values()))


def _distinct(sessions: Sequence[SessionVerdict]) -> Dict[str, ConversationVerdict]:
    return {c.conversation_id: c for s in sessions for c in s.conversations if c.on_disk}


def _page_bounds(cursor: Optional[str], limit: int, total: int) -> Tuple[int, int]:
    start = int(cursor) if cursor else 0
    if start < 0:
        raise ReportError("cursor must not be negative")
    return start, min(total, start + limit)


def build_page(evaluator: Evaluator, ready: Readiness, idle_days: int, cursor: Optional[str], limit: int) -> Page:
    verdicts = evaluator.sessions()
    offloadable = [v for v in verdicts if v.offloadable and ready.ready]
    idle = [v for v in offloadable if (evaluator.idle_days(v.idle_epoch) or 0.0) >= idle_days]
    idle.sort(key=lambda v: (v.idle_epoch if v.idle_epoch is not None else 0.0, v.session_uuid))
    quiet = {c.conversation_id: c for c in evaluator.no_session() if c.on_disk and c.eligible and ready.ready
             and (evaluator.idle_days(c.newest_mtime) or 0.0) >= idle_days}
    blocked = Counter(r for v in verdicts if not v.offloadable for r in v.reasons)
    start, end = _page_bounds(cursor, limit, len(idle))
    return Page(ready, idle_days, _totals(len(idle), _distinct(idle)), _totals(len(offloadable), _distinct(offloadable)),
                _totals(0, quiet), dict(sorted(blocked.items())), idle[start:end], str(end) if end < len(idle) else None, len(idle))
