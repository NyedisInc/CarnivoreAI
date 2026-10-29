
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Set

import structlog

from src.core.attention.evidence import REASON_INPUT, STATE_BUSY, STATE_DONE_IDLE, STATE_NEEDS_USER
from src.core.attention_history import store as S

logger = structlog.get_logger()

Resolver = Callable[[str, str], Optional[str]]


def kind_for(state: str, reason: str) -> Optional[str]:
    if state == STATE_DONE_IDLE:
        return S.KIND_DONE
    if state == STATE_BUSY:
        return S.KIND_BUSY
    if state == STATE_NEEDS_USER:
        return S.KIND_NOTICE if reason == REASON_INPUT else S.KIND_QUESTION
    return None


def resolve_from_datastore(db: Path, key: str, session_id: str) -> Optional[str]:
    name, _, epoch = key.rpartition("@")
    if not name:
        name, epoch = key, ""
    sql, params = "SELECT session_uuid FROM sessions WHERE host_key = 'local' AND tmux_name = ?", [name]
    if epoch.isdigit():
        sql, params = sql + " AND tmux_created_epoch = ?", params + [int(epoch)]
    try:
        with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)) as conn:
            row = conn.execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()
    except sqlite3.Error as exc:
        logger.warning("attention_history_uuid_unread", error=type(exc).__name__)
        return None
    return str(row[0]) if row and row[0] else None


class EdgeRecorder:

    def __init__(self, store: S.AttentionHistoryStore, resolve: Resolver, *,
                 submit: Callable[..., Any] = lambda fn, *args: fn(*args),
                 announce: Callable[[], None] = lambda: None) -> None:
        self._store, self._resolve, self._submit, self._announce = store, resolve, submit, announce
        self._in_startup: Set[str] = set()

    def on_transition(self, target: Any, transition: Any) -> None:
        kind = kind_for(transition.state, transition.reason)
        if kind is not None:
            self._submit(self._write, target.session_id, target.key, kind, transition.at)

    def on_observation(self, target: Any, observation: Any) -> None:
        from src.core.attention.startup_screen import shown_screen  # noqa: PLC0415

        if shown_screen(observation) is None:
            self._in_startup.discard(target.key)
        elif target.key not in self._in_startup:
            self._in_startup.add(target.key)
            self._submit(self._write, target.session_id, target.key, S.KIND_STARTUP, observation.observed_at)

    def _write(self, session_id: str, key: str, kind: str, at: datetime) -> None:
        try:
            session_uuid = self._resolve(session_id, key)
            if session_uuid is not None and self._store.record(session_uuid, kind, at):
                self._announce()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("attention_history_write_failed", kind=kind, error=type(exc).__name__)
