"""Index the bytes appended to ONE live transcript file since its watermark (section 1.13).

APPEND ONLY: the file's new complete lines become new rows and postings; no existing row is touched. The
rows point at the LIVE FILE (``frame_offset`` = the line's byte offset, ``frame_len`` = its length), so a
hit opens by reading that one line back; there is no second copy of the text anywhere.

THE FALLBACK. A watermark that no longer holds (the offset is past the end, or the last indexed line is not
where it was: a truncation or a rewrite), or a filter rule change, reads the file WHOLE from byte 0 under
the same filter, after removing what was indexed from it (the file's rows in the cache).

SUBAGENT FILES keep their sidechain records: the ``sidechain`` rule is about subagent chatter inside the MAIN
transcript (``rules.py``), and every record of a subagent file is a sidechain record.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.deepsearch import constants as K
from src.core.deepsearch import indexer as point_indexer
from src.core.deepsearch import rules as rules_mod
from src.core.deepsearch.extract import extract
from src.core.deepsearch.live import store
from src.core.deepsearch.live.reader import RangeReader
from src.core.deepsearch.live.watermark import FULL_START, Start, verify
from src.core.transcript_source import constants as TS
from src.core.deepsearch.byte_source import ByteSource

logger = structlog.get_logger()


@dataclass(frozen=True)
class FileSpec:

    conversation_id: str
    path: str
    file_kind: str
    family: str
    planned_end: Optional[int] = None


@dataclass
class FileResult:

    path: str
    file_kind: str
    mode: Optional[str] = None
    reason: Optional[str] = None
    start: int = 0
    end: int = 0
    lines: int = 0
    rows: int = 0
    bytes_read: int = 0
    last_serial: Optional[str] = None
    skipped: Optional[str] = None
    checked_bytes: int = 0

    def output(self) -> Dict[str, Any]:
        out = {"path": self.path, "file_kind": self.file_kind, "mode": self.mode, "reason": self.reason,
               "start": self.start, "end": self.end, "lines": self.lines, "rows": self.rows,
               "bytes_read": self.bytes_read, "checked_bytes": self.checked_bytes, "last_serial": self.last_serial}
        if self.skipped:
            out["skipped"] = self.skipped
        return out


def rules_for(overrides: Optional[Dict[str, Any]], family: str, file_kind: str) -> Dict[str, Any]:
    rules = rules_mod.effective(overrides, family)
    return {**rules, "sidechain": K.KEEP} if file_kind == K.FILE_SUBAGENT else rules


def in_scope(scope: str, spec: FileSpec, head: Optional[bytes] = None) -> bool:
    from src.core.transcript_source import scope as scope_mod

    if spec.file_kind == K.FILE_SUBAGENT:
        return scope_mod.includes_subagents(scope)
    return scope_mod.includes_session(scope, spec.family, Path(spec.path), head)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def index_file(conn: sqlite3.Connection, spec: FileSpec, *, overrides: Optional[Dict[str, Any]],
               scope: str, source: Optional[ByteSource] = None, mark: Optional[str] = None) -> FileResult:
    from src.core.db import transaction
    from src.core.transcript_manifest.tail import line_serial

    result = FileResult(spec.path, spec.file_kind)
    path = Path(spec.path)
    live = store.get(conn, spec.path)
    if live is not None and live.scope == scope and not live.in_scope:
        result.skipped = K.SKIP_LIVE_OUT_OF_SCOPE
        return result
    now = _utc_now()
    head = None
    if source is not None and spec.file_kind != K.FILE_SUBAGENT and (live is None or live.scope != scope):
        head = source.read(0, TS.ENTRYPOINT_SCAN_BYTES)
    if (live is None or live.scope != scope) and not in_scope(scope, spec, head):
        with transaction(conn):
            if live is not None:
                store.delete_file(conn, int(live.id))
            store.save(conn, store.LiveFile(spec.conversation_id, spec.path, spec.file_kind, spec.family, 0, 0, mark,
                                            0, 0, None, None, 0, "", 0, scope, now, now))
        result.skipped = K.SKIP_LIVE_OUT_OF_SCOPE
        return result
    size = os.stat(path).st_size if source is None else source.length
    version = rules_mod.version_of(overrides, spec.family)
    stale_id = int(live.id) if live is not None and not live.in_scope else None
    if stale_id is not None:
        live = None
    if live is not None and live.filter_version != version:
        start = Start(K.MODE_FULL, 0, 0, K.FULL_FILTER_CHANGED)
    elif live is not None:
        start = verify(path if source is None else source, size, live.indexed_offset, live.indexed_lines, live.last_serial, live.last_serial_offset)
    else:
        start = FULL_START
    rules = rules_for(overrides, spec.family, spec.file_kind)
    end = size if spec.planned_end is None else min(size, max(int(spec.planned_end), start.offset))
    reader = RangeReader(path if source is None else source, start.offset, end)
    pending: List[Tuple[tuple, str]] = []
    last: Optional[Tuple[int, bytes]] = None
    for number, (offset, line) in enumerate(reader, start=start.lines):
        last = (offset, line)
        found = extract(line, rules, spec.family)
        if found is not None:
            pending.append(((0, offset, len(line), number, number, found[0]), found[1]))
    result.mode, result.reason = start.mode, start.reason
    result.start, result.end, result.lines, result.rows = start.offset, reader.end_offset, reader.lines, len(pending)
    result.bytes_read = reader.bytes_read
    result.checked_bytes = start.checked_bytes
    with transaction(conn):
        if stale_id is not None:
            store.delete_file(conn, stale_id)
        if start.mode == K.MODE_FULL:
            if live is not None:
                store.delete_file(conn, int(live.id))
            live = None
        if live is None:
            live = store.LiveFile(spec.conversation_id, spec.path, spec.file_kind, spec.family, start.offset,
                                  start.lines, None, start.offset, start.lines, None, None, 0, version, 1, scope,
                                  now, now)
        live.indexed_offset, live.indexed_lines = reader.end_offset, start.lines + reader.lines
        if last is not None:
            live.last_serial, live.last_serial_offset = line_serial(last[1][:-1]), last[0]
            live.indexed_at = now
        live.rows += len(pending)
        live.filter_version, live.in_scope, live.scope = version, 1, scope
        live.base_point_id = mark
        live_id = store.save(conn, live)
        point_indexer.write_rows(conn, K.LIVE_DOC_ID, pending, live_id)
    result.last_serial = live.last_serial
    if not reader.lines and start.mode == K.MODE_APPEND:
        result.skipped = K.SKIP_LIVE_NOTHING_NEW
    return result
