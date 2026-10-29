from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from typing import Any

import structlog

from src.core.session_token_usage.model_table import readable_model_name

from .store import StatsStore

logger = structlog.get_logger()

KINDS = frozenset({
    "session_created", "session_finished", "account_switched",
    "model_first_seen", "collector_stale", "tripwire_fired", "tripwire_resolved",
})
MAX_DATA_BYTES = 512
_ID = re.compile(r"[A-Za-z0-9_.:@=-]{1,128}")
_bound: StatsStore | None = None


def bind(store: StatsStore | None) -> None:
    global _bound
    _bound = None if os.environ.get("CLOUDE_TEST_MODE") else store


def _clean(data: dict[str, Any] | None) -> str | None:
    out: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if not isinstance(key, str) or not _ID.fullmatch(key):
            return None
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str) and _ID.fullmatch(value):
            out[key] = value
        else:
            return None
    text = json.dumps(out, separators=(",", ":"), sort_keys=True)
    return text if len(text) <= MAX_DATA_BYTES else None


def record(kind: str, subject: str = "", data: dict[str, Any] | None = None, *,
           store: StatsStore | None = None, occurred_at: int | None = None) -> bool:
    target = store or _bound
    payload = _clean(data)
    if target is None or kind not in KINDS or payload is None or (
            subject and not _ID.fullmatch(subject)):
        return False
    try:
        with target.connect() as conn:
            row = conn.execute("SELECT enabled FROM stats_settings WHERE singleton=1").fetchone() \
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='stats_settings'").fetchone() else None
            if row is not None and not row[0]:
                return False
            conn.execute("INSERT INTO stats_events(occurred_at,kind,subject,data) VALUES (?,?,?,?)",
                         (int(occurred_at if occurred_at is not None else time.time()), kind, subject, payload))
        return True
    except sqlite3.Error as exc:
        logger.warning("stats_event_failed", kind=kind, error_type=type(exc).__name__)
        return False


def record_soon(kind: str, subject: str = "", data: dict[str, Any] | None = None) -> None:
    if _bound is None:
        return
    try:
        asyncio.get_running_loop().run_in_executor(None, lambda: record(kind, subject, data))
    except RuntimeError:
        record(kind, subject, data)


def note_models(conn: sqlite3.Connection, models: set[str]) -> None:
    fresh = []
    for model in sorted(m for m in models if m and m != "<synthetic>"):
        cursor = conn.execute("INSERT OR IGNORE INTO stats_models_seen VALUES (?,?)",
                              (model, int(time.time())))
        if cursor.rowcount:
            fresh.append(model)
    for model in fresh:
        if _ID.fullmatch(model):
            conn.execute("INSERT INTO stats_events(occurred_at,kind,subject,data) VALUES (?,?,?,?)",
                         (int(time.time()), "model_first_seen", model,
                          json.dumps({"model": model}, separators=(",", ":"))))


def initialize_models(store: StatsStore) -> None:
    with store.connect() as conn:
        if conn.execute("SELECT 1 FROM stats_meta WHERE key='models_seeded'").fetchone():
            return
        conn.execute("""INSERT OR IGNORE INTO stats_models_seen
            SELECT model,MIN(minute_ts) FROM minute_usage WHERE model!='' GROUP BY model""")
        conn.execute("INSERT INTO stats_meta(key,value) VALUES ('models_seeded','1')")


def _subject_label(kind: str, subject: str) -> str:
    return (readable_model_name(subject) or subject) if kind == "model_first_seen" else subject


def list_events(store: StatsStore, *, start: int, end: int, kind: str | None,
                limit: int, cursor: int) -> dict:
    if kind is not None and kind not in KINDS:
        raise ValueError("unknown event kind")
    where, args = "occurred_at>=? AND occurred_at<?", [start, end]
    if kind:
        where += " AND kind=?"
        args.append(kind)
    with store.connect(readonly=True) as conn:
        rows = conn.execute(
            f"SELECT id,occurred_at,kind,subject,data FROM stats_events WHERE {where} "
            "ORDER BY occurred_at DESC,id DESC LIMIT ? OFFSET ?", (*args, limit + 1, cursor)).fetchall()
    return {"items": [{"id": r["id"], "occurred_at": r["occurred_at"], "kind": r["kind"],
                       "subject": r["subject"], "label": _subject_label(r["kind"], r["subject"]),
                       "data": json.loads(r["data"])} for r in rows[:limit]],
            "next_cursor": cursor + limit if len(rows) > limit else None}
