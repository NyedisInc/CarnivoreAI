
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from collections import OrderedDict
from typing import Iterator, List, Optional, Sequence, Tuple

import structlog

from src.core.pipeline import contract as C
from src.core.timeline import index
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import MAX_LINE_BYTES, extract_line
from src.core.timeline.model import FILE_KEY_MAIN, Kind, TimelineEvent, is_ident
from src.core.transcript_contract.lines import RangeLine
from src.core.transcript_manifest.tail import line_serial, read_last_line, serial_of_record

log = structlog.get_logger()

PLUGIN_ID = "timeline"
DB_NAME = "timeline.db"
SWITCH_ID = "sessionchat"
SUBAGENT_PREFIX = "agent-"
CONTEXT_CACHE_FILES = 64

_contexts: "OrderedDict[str, Tuple[int, ExtractContext]]" = OrderedDict()
_contexts_lock = threading.Lock()


def real_path_of(path: str) -> str:
    return os.path.realpath(path)


def file_key_of(path: str, file_kind: str) -> str:
    if file_kind != C.FILE_SUBAGENT:
        return FILE_KEY_MAIN
    stem = os.path.basename(path).removesuffix(".jsonl")
    return stem.removeprefix(SUBAGENT_PREFIX)


def _take_context(real: str, at: int) -> Optional[ExtractContext]:
    with _contexts_lock:
        held = _contexts.pop(real, None)
    return held[1] if held is not None and held[0] == at else None


def _keep_context(real: str, at: int, ctx: ExtractContext) -> None:
    with _contexts_lock:
        _contexts[real] = (at, ctx)
        while len(_contexts) > CONTEXT_CACHE_FILES:
            _contexts.popitem(last=False)


def _forget_context(real: str) -> None:
    with _contexts_lock:
        _contexts.pop(real, None)


def _disk_lines(path: str, start: int, stop: int, budget: Optional[int] = None) -> Iterator[Tuple[int, bytes]]:
    with open(path, "rb") as handle:
        handle.seek(start)
        offset = start
        while offset < stop and (budget is None or offset - start < budget or offset == start):
            raw = handle.readline()
            if not raw.endswith(b"\n"):
                return
            yield offset, raw
            offset += len(raw)


def _extract(ctx: ExtractContext, raw: bytes, offset: int, conv: str, serial: Optional[str] = None) -> List[TimelineEvent]:
    body = raw[:-1] if raw.endswith(b"\n") else raw
    if serial is None and len(body) > MAX_LINE_BYTES:
        serial = line_serial(body)
    try:
        return extract_line(ctx, body, offset + len(raw), serial=serial)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        log.warning("timeline_extract_failed", conv=conv, file_key=ctx.file_key, offset=offset, error=type(exc).__name__,
                    detail=str(exc)[:300])
        return []


def _replay(ctx: ExtractContext, path: str, start: int, upto: int, budget: Optional[int] = None) -> Tuple[int, int]:
    reached = start
    try:
        for offset, raw in _disk_lines(path, start, upto, budget):
            _extract(ctx, raw, offset, ctx.conv)
            reached = offset + len(raw)
    except OSError as exc:
        log.warning("timeline_replay_unreadable", conv=ctx.conv, path_tail=os.path.basename(path), error=type(exc).__name__)
        return reached - start, upto
    return reached - start, reached


def _new_context(event: C.Appended) -> ExtractContext:
    return ExtractContext(conv=event.conversation_id, file_key=file_key_of(event.path, event.file_kind), family=event.family)


def _serial_of_line(line: RangeLine) -> str:
    body = line.raw[:-1] if line.raw.endswith(b"\n") else line.raw
    return serial_of_record(line.parsed.raw, body)


def _lines_to_index(event: C.Appended, indexed_to: int) -> List[Tuple[int, bytes, Optional[str]]]:
    lines: List[Tuple[int, bytes, Optional[str]]] = []
    if event.start > indexed_to:
        try:
            lines.extend((off, raw, None) for off, raw in _disk_lines(event.path, indexed_to, event.start))
        except OSError as exc:
            log.warning("timeline_gap_unreadable", conv=event.conversation_id, error=type(exc).__name__)
    lines.extend((line.offset, line.raw, _serial_of_line(line)) for line in event.lines if line.offset >= indexed_to)
    return lines


def _is_stale(row: tuple, event: C.Appended) -> bool:
    _, _, indexed_to, gone, last_serial = row
    if event.start != 0 or indexed_to == 0:
        return False
    if gone:
        return True
    try:
        if os.path.getsize(event.path) < indexed_to:
            return True
        last = read_last_line(Path(event.path), indexed_to)
    except OSError:
        return False
    if last.end is None:
        return False
    comparable = last_serial is not None and is_ident(last.serial)
    return last.end != indexed_to or (comparable and last.serial != last_serial)


def _peek_context(real: str) -> Optional[Tuple[int, ExtractContext]]:
    with _contexts_lock:
        return _contexts.get(real)


def catch_up(conn: sqlite3.Connection, event: C.Appended, limit: int) -> C.CatchUp:
    real = real_path_of(event.path)
    row = index.file_row(conn, real)
    indexed_to = row[2] if row else 0
    if row is None or indexed_to == 0 or event.end <= indexed_to or _is_stale(row, event):
        return C.CatchUp(True)
    held = _peek_context(real)
    if held is not None and held[0] == indexed_to:
        return C.CatchUp(True)
    start, ctx = (held[0], held[1]) if held is not None and held[0] < indexed_to else (0, _new_context(event))
    read, reached = _replay(ctx, event.path, start, indexed_to, limit)
    _keep_context(real, reached, ctx)
    return C.CatchUp(reached >= indexed_to, read)


def _fork_marker_only(events: List[TimelineEvent]) -> List[TimelineEvent]:
    return [event.model_copy(update={"turn": None}) for event in events if event.kind is Kind.CONVERSATION_SWITCH]


def _restart_stale(conn: sqlite3.Connection, real: str, row: tuple) -> None:
    _forget_context(real)
    index.drop_file_rows(conn, row[0])


def _appended(conn: sqlite3.Connection, event: C.Appended) -> None:
    real = real_path_of(event.path)
    conv_id = index.conv_id_of(conn, event.conversation_id, event.family)
    row = index.file_row(conn, real)
    if row and _is_stale(row, event):
        _restart_stale(conn, real, row)
        row = index.file_row(conn, real)
    file_id = row[0] if row else index.add_file(conn, conv_id, real, file_key_of(event.path, event.file_kind), event.file_kind)
    indexed_to = row[2] if row else 0
    if event.end <= indexed_to:
        return
    ctx = _take_context(real, indexed_to)
    if ctx is None:
        ctx = _new_context(event)
        _replay(ctx, event.path, 0, indexed_to)
    last: Optional[Tuple[bytes, Optional[str]]] = None
    for offset, raw, serial in _lines_to_index(event, indexed_to):
        events = _extract(ctx, raw, offset, event.conversation_id, serial)
        if event.inherited_start <= offset < event.inherited_end:
            events = _fork_marker_only(events)
        index.apply_events(conn, conv_id, file_id, events, offset)
        last = (raw, serial)
    index.advance(conn, file_id, event.end, _last_serial(last))
    _keep_context(real, event.end, ctx)


def _last_serial(last: Optional[Tuple[bytes, Optional[str]]]) -> Optional[str]:
    if last is None:
        return None
    raw, serial = last
    line = raw[:-1] if raw.endswith(b"\n") else raw
    serial = serial or line_serial(line)
    return serial if is_ident(serial) else serial_of_record(None, line)


def _reset(conn: sqlite3.Connection, event: C.FileReset) -> None:
    real = real_path_of(event.path)
    _forget_context(real)
    row = index.file_row(conn, real)
    if row:
        index.drop_file_rows(conn, row[0])


def _removed(conn: sqlite3.Connection, event: C.FileRemoved) -> None:
    real = real_path_of(event.path)
    _forget_context(real)
    row = index.file_row(conn, real)
    if row:
        index.mark_gone(conn, row[0])


def on_events(conn: sqlite3.Connection, events: Sequence[C.Event]) -> None:
    for event in events:
        if isinstance(event, C.Appended):
            _appended(conn, event)
        elif isinstance(event, C.FileReset):
            _reset(conn, event)
        elif isinstance(event, C.FileRemoved):
            _removed(conn, event)


TIMELINE = C.Plugin(id=PLUGIN_ID, db_name=DB_NAME, schema_version=index.SCHEMA_VERSION, migrate=index.migrate,
                    on_events=on_events, catch_up=catch_up, families=frozenset({C.FAMILY_CLAUDE}), per_file_removal=True,
                    switch_id=SWITCH_ID)
