
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

from src.core.timeline import agent_tail, bodies, cursor as cursors, files, gate, hot, index_read, paging, reading, resolve, rewind, subscribe
from src.core.timeline import state as state_projection
from src.core.timeline.facts_adapter import facts_from_state
from src.core.timeline.model import (
    FILE_KEY_MAIN, LEVEL_RAW, LEVEL_TRACE, LEVEL_WORK, Kind, TimelineEvent,
)

DEFAULT_LEVEL: int = LEVEL_WORK


class NoConversation(LookupError):
    pass


class UnknownConversation(LookupError):
    pass


UnknownTurn = paging.UnknownTurn


class UnknownFile(LookupError):
    pass


def event_json(event: TimelineEvent) -> Dict[str, Any]:
    body = event.model_dump(mode="json")
    body["id"], body["level"] = event.id, event.level
    return body


def _begin(resolved: Any) -> None:
    gate.require_on()
    resolve.require_claude(resolved.row)


def _developer_mode() -> bool:
    from src.plugins.host import developer_mode  # noqa: PLC0415

    return developer_mode.is_on()


def _state_dir() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.get_state_dir())


def _conv_of(resolved: Any, conv: Optional[str]) -> str:
    from src.core.session_timeline import gather  # noqa: PLC0415

    if conv is None:
        if not resolved.conv:
            raise NoConversation("this session has no conversation yet")
        return resolved.conv
    if conv == resolved.conv:
        return conv
    _row, held = gather.conversations_of(resolved.row.session_uuid)
    if conv not in held:
        raise UnknownConversation("that conversation does not belong to this session")
    return conv


def _file(resolved: Any, conv: str, file_key: str) -> str:
    main = files.main_file(conv, resolved.row.working_dir)
    if file_key == FILE_KEY_MAIN:
        return main
    found = files.agent_files(main).get(file_key)
    if found is None:
        raise UnknownFile("that sub-agent file does not exist")
    return found


def _filtered(events: List[TimelineEvent], kinds: Optional[FrozenSet[Kind]], thread: Optional[str], turn: Optional[int],
              level: int) -> List[TimelineEvent]:
    return [e for e in events if e.level <= level and (kinds is None or e.kind in kinds)
            and (thread is None or e.thread == thread) and (turn is None or e.turn == turn)]


def _level(asked: Optional[int]) -> int:
    level = DEFAULT_LEVEL if asked is None else asked
    return level if level < LEVEL_RAW or _developer_mode() else LEVEL_TRACE


def _forward(resolved: Any, conv: str, file_key: str, after: Optional[cursors.Cursor], limit: int) -> Dict[str, Any]:
    real = _file(resolved, conv, file_key)
    page = reading.read_forward(real, conv, file_key, after, limit=limit)
    nxt = None if page.reset or page.end == 0 else cursors.Cursor(conv, file_key, page.end, page.last_serial or "").wire()
    return {"events": page.events, "next": nxt, "end": page.at_end, "reset": page.reset, "next_before": None, "indexing": None,
            "size": page.size, "chips": []}


def events(resolved: Any, *, after: Optional[str] = None, before_turn: Optional[int] = None, limit: Optional[int] = None,
           kinds: Optional[FrozenSet[Kind]] = None, thread: Optional[str] = None, turn: Optional[int] = None,
           level: Optional[int] = None, conv: Optional[str] = None, include_abandoned: bool = False) -> Dict[str, Any]:
    _begin(resolved)
    start = cursors.parse(after) if after else None
    conv = _conv_of(resolved, start.conv if start else conv)
    shown = _level(level)
    main_real = _file(resolved, conv, FILE_KEY_MAIN)
    selected = files.file_for_thread(main_real, thread)
    if selected is None:
        raise UnknownFile("that sub-agent file does not exist")
    file_key = start.file_key if start else selected[0]
    if start or file_key != FILE_KEY_MAIN:
        page = _forward(resolved, conv, file_key, start, limit or reading.DEFAULT_PAGE_EVENTS)
    elif turn is not None:
        page = paging.one_turn(_state_dir(), main_real, conv, resolved.row_family, turn)
    else:
        page = paging.backward(_state_dir(), main_real, conv, resolved.row_family, before_turn, limit)
    flagged: FrozenSet[str] = frozenset()
    if file_key == FILE_KEY_MAIN:
        page["events"], flagged = rewind.annotate(page["events"], rewind.map_for(main_real), include_abandoned)
    kept = _filtered(page["events"], kinds, thread, turn, shown)
    return {"session_uuid": resolved.row.session_uuid, "conv": conv, "file_key": file_key, **page,
            "events": [{**event_json(e), **({"abandoned": True} if e.id in flagged else {})} for e in kept]}


def body(resolved: Any, event_id: str) -> Dict[str, Any]:
    _begin(resolved)
    ident = bodies.parse_event_id(event_id)
    conv = _conv_of(resolved, ident.conv)
    got = bodies.read_body(_file(resolved, conv, ident.file_key), ident, resolved.row_family)
    return {"session_uuid": resolved.row.session_uuid, **got, "event": event_json(got["event"])}


def turns(resolved: Any, *, before: Optional[int] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    _begin(resolved)
    conv = _conv_of(resolved, None)
    size = os.stat(_file(resolved, conv, FILE_KEY_MAIN)).st_size
    wanted = min(limit or index_read.DEFAULT_TURNS, index_read.MAX_WANTED_TURNS)
    rows = index_read.turn_rows(_state_dir(), conv, before, wanted + 1) or []
    pct = index_read.indexed_percent(_state_dir(), conv, size)
    return {"session_uuid": resolved.row.session_uuid, "conv": conv, "turns": rows[:wanted],
            "next_before": rows[wanted - 1]["turn"] if len(rows) > wanted else None, "indexing": {"pct": pct} if pct != 100 else None}


def threads(resolved: Any) -> Dict[str, Any]:
    _begin(resolved)
    conv = _conv_of(resolved, None)
    size = os.stat(_file(resolved, conv, FILE_KEY_MAIN)).st_size
    found = index_read.thread_rows(_state_dir(), conv) or {"threads": [], "todo": None}
    pct = index_read.indexed_percent(_state_dir(), conv, size)
    return {"session_uuid": resolved.row.session_uuid, "conv": conv, **found, "indexing": {"pct": pct} if pct != 100 else None}


def state(resolved: Any) -> Dict[str, Any]:
    _begin(resolved)
    conv = _conv_of(resolved, None)
    real = _file(resolved, conv, FILE_KEY_MAIN)
    epoch = subscribe.PUSH.epoch_of(resolved.row.session_uuid)
    seq = subscribe.PUSH.seq_of(resolved.row.session_uuid)
    size = os.stat(real).st_size

    def project(state_: Any, serial: Optional[str]) -> Dict[str, Any]:
        facts = facts_from_state(state_, size=state_.cursor)
        return {"transcript": state_projection.transcript_fields(state_, facts), "offset": state_.cursor, "serial": serial}

    held = hot.DRIVER.with_state(real, project)
    source = "hot"
    if held is None:
        window, serial = hot.fold_window(real, size)
        held, source = project(window, serial), "read"
    cursor = cursors.Cursor(conv, FILE_KEY_MAIN, held["offset"], held["serial"] or "")
    main_pos = [held["offset"], held["serial"]]
    agent_positions, agent_total = agent_tail.file_positions(real)
    return {"session_uuid": resolved.row.session_uuid, "conv": conv, "family": resolved.row_family, "source": source, "epoch": epoch, "seq": seq,
            "pos": {FILE_KEY_MAIN: main_pos, "cursor": cursor.wire() if held["offset"] else None},
            "files": {FILE_KEY_MAIN: main_pos, **agent_positions}, "files_total": 1 + agent_total,
            "files_more": agent_total > len(agent_positions),
            "transcript": held["transcript"], "live": _live(resolved.info)}


def _live(info: Optional[resolve.LiveRef]) -> Optional[Dict[str, Any]]:
    return info.lights() if info is not None else None
