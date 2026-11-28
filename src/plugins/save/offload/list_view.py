
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import structlog

from src.plugins.save.offload import constants as C
from src.plugins.save.offload.ledger import Entry


class ListViewError(ValueError):
    pass


logger = structlog.get_logger()

KIND_SESSION = "session"
KIND_CONVERSATION = "conversation"
_SEVERITY: Tuple[str, ...] = (C.STATE_FAILED, C.STATE_CONFLICT, C.STATE_RESTORING, C.STATE_OFFLOADING, C.STATE_OFFLOADED)


@dataclass
class Row:

    kind: str
    session_uuid: Optional[str]
    conversation_id: Optional[str]
    title: Optional[str]
    project_id: Optional[int]
    project: Optional[str]
    conversations: int
    bytes: int
    offloaded_at: float
    state: str
    error: str = ""
    error_code: str = ""
    error_path: str = ""


@dataclass
class Totals:

    rows: int = 0
    conversations: int = 0
    bytes: int = 0


@dataclass
class Page:

    rows: List[Row] = field(default_factory=list)
    totals: Totals = field(default_factory=Totals)
    next_cursor: Optional[str] = None


def _worst(states: Iterable[str]) -> str:
    held = set(states)
    return next(s for s in _SEVERITY if s in held)


def _row(kind: str, key: str, entries: List[Entry], names: Dict[str, Tuple[Optional[str], Optional[int]]], projects: Dict[int, str]) -> Row:
    title, project_id = names.get(key, (None, None)) if kind == KIND_SESSION else (None, None)
    state = _worst(e.state for e in entries)
    why = next((e for e in entries if (e.error or e.error_code) and e.state in (C.STATE_FAILED, C.STATE_CONFLICT)), None)
    return Row(kind=kind, session_uuid=key if kind == KIND_SESSION else None, conversation_id=key if kind == KIND_CONVERSATION else None, title=title,
               project_id=project_id, project=projects.get(project_id) if project_id is not None else None, conversations=len(entries),
               bytes=sum(e.bytes for e in entries), offloaded_at=max(e.offloaded_at for e in entries), state=state,
               error=why.error if why else "", error_code=why.error_code if why else "", error_path=why.error_path if why else "")


def group_rows(entries: Iterable[Entry], names: Dict[str, Tuple[Optional[str], Optional[int]]], projects: Dict[int, str], state: Optional[str] = None) -> Tuple[List[Row], Totals]:
    by_session: Dict[str, List[Entry]] = {}
    loose: List[Entry] = []
    for entry in entries:
        if not entry.group:
            loose.append(entry)
        for session in entry.group:
            by_session.setdefault(session, []).append(entry)
    held = [(_row(KIND_SESSION, s, es, names, projects), es) for s, es in by_session.items()]
    held.sort(key=lambda pair: (-pair[0].offloaded_at, pair[0].session_uuid or ""))
    alone = [(_row(KIND_CONVERSATION, e.conversation_id, [e], names, projects), [e]) for e in loose]
    alone.sort(key=lambda pair: (-pair[0].offloaded_at, pair[0].conversation_id or ""))
    kept = [pair for pair in held + alone if state is None or pair[0].state == state]
    distinct = {e.conversation_id: e for _, es in kept for e in es}
    return [row for row, _ in kept], Totals(rows=len(kept), conversations=len(distinct), bytes=sum(e.bytes for e in distinct.values()))


def page_of(rows: List[Row], totals: Totals, cursor: Optional[str], limit: int) -> Page:
    start = int(cursor) if cursor else 0
    if start < 0:
        raise ListViewError("cursor must not be negative")
    end = start + limit
    return Page(rows=rows[start:end], totals=totals, next_cursor=str(end) if end < len(rows) else None)
