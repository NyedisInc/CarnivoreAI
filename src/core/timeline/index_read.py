
from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional

import structlog

from src.core.safe_io.readonly_db import connect_readonly
from src.core.pipeline import plugin_db
from src.core.timeline.model import FILE_KEY_MAIN, NO_TURN_BOUND
from src.core.timeline.plugin import TIMELINE

log = structlog.get_logger(__name__)

DEFAULT_TURNS: int = 20
MAX_TURNS: int = 200
MAX_WANTED_TURNS: int = MAX_TURNS - 1
MAX_THREADS: int = 500


class TurnSpan(NamedTuple):

    turn: int
    start_off: int
    end_off: int


@contextmanager
def _open(state_dir: Path) -> Iterator[Optional[sqlite3.Connection]]:
    path = plugin_db.db_path(state_dir, TIMELINE)
    if not path.exists():
        yield None
        return
    try:
        conn = connect_readonly(path, timeout=5.0)
    except sqlite3.Error as exc:
        log.warning("timeline_index_unreadable", error=type(exc).__name__)
        yield None
        return
    with closing(conn):
        yield conn


def _main_file(conn: sqlite3.Connection, conv: str) -> Optional[tuple]:
    return conn.execute("SELECT f.file_id, f.conv_id, f.indexed_to, f.gone FROM files f JOIN convs c ON c.conv_id = f.conv_id "
                        "WHERE c.conv = ? AND f.file_key = ? ORDER BY f.file_id LIMIT 1", (conv, FILE_KEY_MAIN)).fetchone()


def indexed_percent(state_dir: Path, conv: str, size: int) -> Optional[int]:
    try:
        with _open(state_dir) as conn:
            row = _main_file(conn, conv) if conn is not None else None
    except sqlite3.Error as exc:
        log.debug("timeline_index_no_tables", error=type(exc).__name__)
        return None
    if row is None:
        return None
    return 100 if size <= 0 else min(100, row[2] * 100 // size)


def turns_before(state_dir: Path, conv: str, before_turn: Optional[int], limit: int = DEFAULT_TURNS) -> Optional[List[TurnSpan]]:
    limit = max(1, min(limit, MAX_TURNS))
    try:
        with _open(state_dir) as conn:
            row = _main_file(conn, conv) if conn is not None else None
            if row is None:
                return None
            found = conn.execute("SELECT turn, start_off, end_off FROM turns WHERE file_id = ? AND turn < ? "
                                 "ORDER BY turn DESC LIMIT ?", (row[0], before_turn if before_turn is not None else NO_TURN_BOUND, limit))
            return [TurnSpan(*r) for r in found]
    except sqlite3.Error as exc:
        log.debug("timeline_index_no_tables", error=type(exc).__name__)
        return None


def turn_rows(state_dir: Path, conv: str, before: Optional[int], limit: int) -> Optional[List[Dict[str, Any]]]:
    limit = max(1, min(limit, MAX_TURNS))
    try:
        with _open(state_dir) as conn:
            row = _main_file(conn, conv) if conn is not None else None
            if row is None:
                return None
            cursor = conn.execute("SELECT turn, start_off, end_off, opened_at, ended_at, end_via, end_kind, origin, plain, calls, "
                                  "top_tools, replies, bytes FROM turns WHERE file_id = ? AND turn < ? ORDER BY turn DESC LIMIT ?",
                                  (row[0], before if before is not None else NO_TURN_BOUND, limit))
            names = [d[0] for d in cursor.description]
            out = []
            for values in cursor:
                item = dict(zip(names, values))
                item["top_tools"] = json.loads(item["top_tools"]) if item["top_tools"] else {}
                item["plain"] = None if item["plain"] is None else bool(item["plain"])
                out.append(item)
            return out
    except sqlite3.Error as exc:
        log.debug("timeline_index_no_tables", error=type(exc).__name__)
        return None


def thread_rows(state_dir: Path, conv: str) -> Optional[Dict[str, Any]]:
    try:
        with _open(state_dir) as conn:
            if conn is None:
                return None
            known = conn.execute("SELECT conv_id FROM convs WHERE conv = ?", (conv,)).fetchone()
            if known is None:
                return None
            found = conn.execute("SELECT t.thread_kind, t.task_id, t.tool_use_id, t.start_off, t.end_off, t.status, f.file_key "
                                 "FROM threads t JOIN files f ON f.file_id = t.file_id WHERE t.conv_id = ? "
                                 "ORDER BY t.start_off LIMIT ?", (known[0], MAX_THREADS))
            names = ["kind", "task_id", "tool_use_id", "start_off", "end_off", "status", "file_key"]
            threads = [dict(zip(names, r)) for r in found]
            todo = conn.execute("SELECT off, data FROM markers WHERE conv_id = ? AND kind = 'todo' ORDER BY off DESC LIMIT 1",
                                (known[0],)).fetchone()
            return {"threads": threads, "todo": {"off": todo[0], **(json.loads(todo[1]) if todo[1] else {})} if todo else None}
    except sqlite3.Error as exc:
        log.debug("timeline_index_no_tables", error=type(exc).__name__)
        return None
