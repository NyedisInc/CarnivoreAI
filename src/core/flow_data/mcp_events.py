
from __future__ import annotations

import contextvars
import queue
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.db import DatastoreError, transaction
from src.core.flow_data import mcp_event_fields
from src.core.flow_data import main_db
from src.core.mcp.caller import AgentCaller

logger = structlog.get_logger()

RETENTION_DAYS = 30
QUEUE_MAX = 5000
BATCH_MAX = 200
READ_MAX = 500

_Event = Tuple[Any, ...]
_queue: "queue.Queue[_Event]" = queue.Queue(maxsize=QUEUE_MAX)
_thread_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_dropped = 0
_FLUSH = "flush"
_gate_denied: "contextvars.ContextVar[bool]" = contextvars.ContextVar("mcp_gate_denied", default=False)


@dataclass(frozen=True)
class Handle:

    call_id: str
    started: float


def _put(event: _Event) -> None:
    global _dropped
    _ensure_thread()
    try:
        _queue.put_nowait(event)
    except queue.Full:
        _dropped += 1
        if _dropped == 1 or _dropped % 1000 == 0:
            logger.warning("mcp_event_queue_full", dropped=_dropped)


def begin(caller: AgentCaller, tool: str, args: Any) -> Handle:
    handle = Handle(secrets.token_hex(8), time.monotonic())
    try:
        kind = 'external' if caller.external else 'pane'
        _put(("start", handle.call_id, time.time(), tool, kind, None if caller.external else caller.current_session_id or None,
              None if caller.external else caller.tmux_name or None, mcp_event_fields.target_ids(args)))
    except (TypeError, AttributeError) as exc:
        logger.warning("mcp_event_begin_failed", tool=tool, error_type=type(exc).__name__)
    return handle


def finish(handle: Handle, result: Any, *, denied_by_gate: bool = False) -> None:
    _put(("end", handle.call_id, mcp_event_fields.outcome_of(result, denied_by_gate),
          int((time.monotonic() - handle.started) * 1000), mcp_event_fields.result_ids(result)))


def mark_gate_denied() -> None:
    _gate_denied.set(True)


def take_gate_denied() -> bool:
    denied = _gate_denied.get()
    _gate_denied.set(False)
    return denied


def flush(timeout: float = 5.0) -> bool:
    done = threading.Event()
    _put((_FLUSH, done))
    return done.wait(timeout)


def _ensure_thread() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    with _thread_lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_drain_forever, name="mcp-event-writer", daemon=True)
            _thread.start()


def _drain_forever() -> None:
    failing = False
    while True:
        batch = [_queue.get()]
        while len(batch) < BATCH_MAX:
            try:
                batch.append(_queue.get_nowait())
            except queue.Empty:
                break
        try:
            _write(batch)
            failing = False
        except (sqlite3.Error, OSError, DatastoreError) as exc:
            if not failing:
                logger.warning("mcp_event_write_failed", error_type=type(exc).__name__, error=str(exc))
            failing = True
        for event in batch:
            if event[0] == _FLUSH:
                event[1].set()


def _write(batch: List[_Event]) -> None:
    rows = [e for e in batch if e[0] != _FLUSH]
    if not rows:
        return
    with closing(main_db.open_main()) as conn, transaction(conn):
        for event in rows:
            if event[0] == "start":
                conn.execute("INSERT INTO mcp_events (call_id, started_at, tool, caller_kind, caller_session_id, caller_tmux, "
                             "target_ids) VALUES (?,?,?,?,?,?,?)", event[1:])
            else:
                conn.execute("UPDATE mcp_events SET outcome=?, duration_ms=?, result_ids=? WHERE call_id=? AND outcome IS NULL",
                             (event[2], event[3], event[4], event[1]))


def prune(now: Optional[float] = None, retention_days: int = RETENTION_DAYS) -> int:
    cutoff = (time.time() if now is None else now) - retention_days * 86400
    with closing(main_db.open_main()) as conn, transaction(conn):
        return conn.execute("DELETE FROM mcp_events WHERE started_at < ?", (cutoff,)).rowcount


def recent(*, tool: Optional[str] = None, session_id: Optional[str] = None, since: float = 0.0,
           limit: int = 100) -> List[Dict[str, Any]]:
    clauses, params = ["started_at >= ?"], [since]
    if tool:
        clauses.append("tool = ?")
        params.append(tool)
    if session_id:
        clauses.append("caller_session_id = ?")
        params.append(session_id)
    with closing(main_db.open_main()) as conn:
        rows = conn.execute(f"SELECT * FROM mcp_events WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                            (*params, max(1, min(int(limit), READ_MAX)))).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]
