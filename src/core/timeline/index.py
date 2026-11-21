
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Iterable, Mapping, Optional

from src.core.timeline.model import Kind, TimelineEvent, is_ident

SCHEMA_VERSION: int = 1

THREAD_AGENT, THREAD_WORKFLOW, THREAD_SHELL, THREAD_MONITOR = "agent", "workflow", "shell", "monitor"
THREAD_KINDS = frozenset({THREAD_AGENT, THREAD_WORKFLOW, THREAD_SHELL, THREAD_MONITOR})
STATUS_RUNNING: str = "running"
THREAD_END_STATUSES = frozenset({"done", "completed", "failed", "killed", "stopped", "cancelled", "canceled", "error",
                                 "timeout"})
STATUS_OTHER: str = "other"
MARKER_GONE: str = "gone"
MARKER_KINDS: Mapping[Kind, str] = {Kind.COMPACTION: "compaction", Kind.CONVERSATION_SWITCH: "switch",
                                    Kind.SUPPRESSED: "suppressed", Kind.TODO: "todo"}
TOOL_COUNTS_MAX: int = 16

_TABLES = (
    "CREATE TABLE IF NOT EXISTS convs (conv_id INTEGER PRIMARY KEY, conv TEXT NOT NULL UNIQUE, family TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS files (file_id INTEGER PRIMARY KEY, conv_id INTEGER NOT NULL, real_path TEXT NOT NULL UNIQUE, "
    "file_key TEXT NOT NULL, file_kind TEXT NOT NULL, last_serial TEXT, indexed_to INTEGER NOT NULL DEFAULT 0, "
    "gone INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS turns (conv_id INTEGER NOT NULL, file_id INTEGER NOT NULL, turn INTEGER NOT NULL, "
    "start_off INTEGER NOT NULL, end_off INTEGER NOT NULL, opened_at TEXT, ended_at TEXT, end_via TEXT, end_kind TEXT, "
    "origin TEXT, plain INTEGER, calls INTEGER NOT NULL DEFAULT 0, top_tools TEXT, replies INTEGER NOT NULL DEFAULT 0, "
    "bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (file_id, turn))",
    "CREATE TABLE IF NOT EXISTS threads (conv_id INTEGER NOT NULL, file_id INTEGER NOT NULL, thread_kind TEXT NOT NULL, "
    "task_id TEXT NOT NULL, tool_use_id TEXT, start_off INTEGER NOT NULL, end_off INTEGER, status TEXT NOT NULL, "
    "PRIMARY KEY (file_id, thread_kind, task_id))",
    "CREATE TABLE IF NOT EXISTS markers (conv_id INTEGER NOT NULL, file_id INTEGER NOT NULL, off INTEGER NOT NULL, "
    "kind TEXT NOT NULL, data TEXT, PRIMARY KEY (file_id, off, kind))",
    "CREATE INDEX IF NOT EXISTS ix_turns_conv ON turns (conv_id, start_off)",
    "CREATE INDEX IF NOT EXISTS ix_threads_conv ON threads (conv_id, start_off)",
    "CREATE INDEX IF NOT EXISTS ix_markers_conv ON markers (conv_id, off)",
)


def migrate(conn: sqlite3.Connection, from_version: int) -> None:
    if from_version < 1:
        for statement in _TABLES:
            conn.execute(statement)


def conv_id_of(conn: sqlite3.Connection, conv: str, family: str) -> int:
    conn.execute("INSERT OR IGNORE INTO convs (conv, family) VALUES (?, ?)", (conv, family))
    return conn.execute("SELECT conv_id FROM convs WHERE conv = ?", (conv,)).fetchone()[0]


def file_row(conn: sqlite3.Connection, real_path: str) -> Optional[tuple]:
    return conn.execute("SELECT file_id, conv_id, indexed_to, gone, last_serial FROM files WHERE real_path = ?", (real_path,)).fetchone()


def add_file(conn: sqlite3.Connection, conv_id: int, real_path: str, file_key: str, file_kind: str) -> int:
    conn.execute("INSERT OR IGNORE INTO files (conv_id, real_path, file_key, file_kind) VALUES (?, ?, ?, ?)",
                 (conv_id, real_path, file_key, file_kind))
    return conn.execute("SELECT file_id FROM files WHERE real_path = ?", (real_path,)).fetchone()[0]


def advance(conn: sqlite3.Connection, file_id: int, indexed_to: int, last_serial: Optional[str]) -> None:
    conn.execute("UPDATE files SET indexed_to = ?, last_serial = COALESCE(?, last_serial), gone = 0 WHERE file_id = ?",
                 (indexed_to, _safe(last_serial), file_id))


def drop_file_rows(conn: sqlite3.Connection, file_id: int) -> None:
    for table in ("turns", "threads", "markers"):
        conn.execute(f"DELETE FROM {table} WHERE file_id = ?", (file_id,))
    conn.execute("UPDATE files SET indexed_to = 0, last_serial = NULL, gone = 0 WHERE file_id = ?", (file_id,))


def mark_gone(conn: sqlite3.Connection, file_id: int) -> None:
    conn.execute("UPDATE files SET gone = 1 WHERE file_id = ?", (file_id,))
    row = conn.execute("SELECT conv_id, indexed_to FROM files WHERE file_id = ?", (file_id,)).fetchone()
    conn.execute("INSERT OR REPLACE INTO markers (conv_id, file_id, off, kind, data) VALUES (?, ?, ?, ?, NULL)",
                 (row[0], file_id, row[1], MARKER_GONE))


def _safe(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return None
    return value if not isinstance(value, str) or is_ident(value) else None


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _touch_turn(conn: sqlite3.Connection, conv_id: int, file_id: int, event: TimelineEvent, line_start: int) -> None:
    conn.execute("INSERT OR IGNORE INTO turns (conv_id, file_id, turn, start_off, end_off, opened_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (conv_id, file_id, event.turn, line_start, event.pos.offset, event.t))
    conn.execute("UPDATE turns SET end_off = MAX(end_off, ?), bytes = MAX(end_off, ?) - start_off WHERE file_id = ? AND turn = ?",
                 (event.pos.offset, event.pos.offset, file_id, event.turn))


def _count_tool(conn: sqlite3.Connection, file_id: int, turn: int, name: Optional[str]) -> None:
    row = conn.execute("SELECT top_tools FROM turns WHERE file_id = ? AND turn = ?", (file_id, turn)).fetchone()
    counts: Dict[str, int] = json.loads(row[0]) if row and row[0] else {}
    if is_ident(name) and (name in counts or len(counts) < TOOL_COUNTS_MAX):
        counts[name] = counts.get(name, 0) + 1
    conn.execute("UPDATE turns SET calls = calls + 1, top_tools = ? WHERE file_id = ? AND turn = ?",
                 (_json(counts), file_id, turn))


def _turn_event(conn: sqlite3.Connection, file_id: int, event: TimelineEvent) -> None:
    data, kind, turn = event.data, event.kind, event.turn
    if kind in (Kind.PROMPT, Kind.COMMAND) and event.pos.offset == turn:
        plain = data.get("plain")
        conn.execute("UPDATE turns SET origin = ?, plain = ? WHERE file_id = ? AND turn = ?",
                     (_safe(data.get("origin")), None if plain is None else int(bool(plain)), file_id, turn))
    elif kind is Kind.REPLY:
        conn.execute("UPDATE turns SET replies = replies + 1 WHERE file_id = ? AND turn = ?", (file_id, turn))
    elif kind is Kind.TOOL_CALL:
        _count_tool(conn, file_id, turn, data.get("name"))
    elif kind is Kind.TURN_END:
        conn.execute("UPDATE turns SET ended_at = ?, end_via = COALESCE(end_via, ?), end_kind = COALESCE(end_kind, ?) "
                     "WHERE file_id = ? AND turn = ?", (event.t, _safe(data.get("via")), _safe(data.get("end")), file_id, turn))


def _launch(conn: sqlite3.Connection, conv_id: int, file_id: int, event: TimelineEvent, line_start: int) -> None:
    data = event.data
    if event.kind is Kind.SUBAGENT_START:
        kind, task = THREAD_AGENT, _safe(data.get("agent_id")) or _safe(data.get("tool_use_id"))
    else:
        kind, task = data.get("bg_kind"), _safe(data.get("task_id")) or _safe(data.get("tool_use_id"))
        kind = kind if kind in THREAD_KINDS else THREAD_SHELL
    if task:
        conn.execute("INSERT OR IGNORE INTO threads (conv_id, file_id, thread_kind, task_id, tool_use_id, start_off, status) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", (conv_id, file_id, kind, task, _safe(data.get("tool_use_id")), line_start,
                                                      STATUS_RUNNING))


def _land(conn: sqlite3.Connection, file_id: int, event: TimelineEvent) -> None:
    data = event.data
    keys = [value for value in (data.get("agent_id"), data.get("task_id"), data.get("tool_use_id")) if is_ident(value)]
    status = data.get("status") or "done"
    status = status if status in THREAD_END_STATUSES else STATUS_OTHER
    for key in keys:
        conn.execute("UPDATE threads SET end_off = ?, status = ? WHERE file_id = ? AND (task_id = ? OR tool_use_id = ?) "
                     "AND status = ?", (event.pos.offset, status, file_id, key, key, STATUS_RUNNING))


def _marker(conn: sqlite3.Connection, conv_id: int, file_id: int, event: TimelineEvent) -> None:
    kept = {key: _safe(value) for key, value in event.data.items() if _safe(value) is not None}
    conn.execute("INSERT OR REPLACE INTO markers (conv_id, file_id, off, kind, data) VALUES (?, ?, ?, ?, ?)",
                 (conv_id, file_id, event.pos.offset, MARKER_KINDS[event.kind], _json(kept) if kept else None))


def apply_events(conn: sqlite3.Connection, conv_id: int, file_id: int, events: Iterable[TimelineEvent], line_start: int) -> None:
    for event in events:
        if event.turn is not None:
            _touch_turn(conn, conv_id, file_id, event, line_start)
            _turn_event(conn, file_id, event)
        if event.kind in (Kind.SUBAGENT_START, Kind.BG_START):
            _launch(conn, conv_id, file_id, event, line_start)
        elif event.kind in (Kind.SUBAGENT_END, Kind.BG_END):
            _land(conn, file_id, event)
        elif event.kind in MARKER_KINDS:
            _marker(conn, conv_id, file_id, event)
