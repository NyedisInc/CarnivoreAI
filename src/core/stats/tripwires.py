from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone

import structlog
from pydantic import ValidationError

from src.models.stats import QueryRequest, TripwireWrite
from . import events, queries
from .config import NotFound

logger = structlog.get_logger()
MAX_TRIPWIRES = 64


def _out(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "chart_id": row["chart_id"], "name": row["name"],
            "query": json.loads(row["query"]), "window_minutes": row["window_minutes"],
            "comparator": row["comparator"], "threshold": row["threshold"],
            "for_minutes": row["for_minutes"], "cooldown_minutes": row["cooldown_minutes"],
            "enabled": bool(row["enabled"]), "state": row["state"], "since": row["since"],
            "last_value": row["last_value"]}


def list_tripwires(store) -> list[dict]:
    with store.connect(readonly=True) as db:
        return [_out(r) for r in db.execute("SELECT * FROM stats_tripwires ORDER BY created_at,id")]


def get_tripwire(store, tripwire_id: str) -> dict:
    with store.connect(readonly=True) as db:
        row = db.execute("SELECT * FROM stats_tripwires WHERE id=?", (tripwire_id,)).fetchone()
    if row is None:
        raise NotFound("tripwire")
    return _out(row)


def _values(config: TripwireWrite) -> tuple:
    return (str(config.chart_id) if config.chart_id else None, config.name,
            json.dumps(config.query, sort_keys=True, separators=(",", ":")),
            config.window_minutes, config.comparator, config.threshold, config.for_minutes,
            config.cooldown_minutes, int(config.enabled))


def create_tripwire(store, config: TripwireWrite) -> dict:
    now, tripwire_id = int(time.time()), str(uuid.uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM stats_tripwires").fetchone()[0] >= MAX_TRIPWIRES:
            raise ValueError("tripwire limit reached")
        db.execute("INSERT INTO stats_tripwires(id,chart_id,name,query,window_minutes,comparator,"
                   "threshold,for_minutes,cooldown_minutes,enabled,state,since,created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,'unknown',?,?)",
                   (tripwire_id, *_values(config), now, now))
    return get_tripwire(store, tripwire_id)


def replace_tripwire(store, tripwire_id: str, config: TripwireWrite) -> dict:
    with store.connect() as db:
        cursor = db.execute(
            "UPDATE stats_tripwires SET chart_id=?,name=?,query=?,window_minutes=?,comparator=?,"
            "threshold=?,for_minutes=?,cooldown_minutes=?,enabled=?,state='unknown',since=?,"
            "pending_since=NULL,last_fired_at=NULL,last_value=NULL WHERE id=?",
            (*_values(config), int(time.time()), tripwire_id))
        if cursor.rowcount != 1:
            raise NotFound("tripwire")
    return get_tripwire(store, tripwire_id)


def delete_tripwire(store, tripwire_id: str) -> None:
    with store.connect() as db:
        if db.execute("DELETE FROM stats_tripwires WHERE id=?", (tripwire_id,)).rowcount != 1:
            raise NotFound("tripwire")


def _measure(store, row: sqlite3.Row, now: float) -> float | None:
    try:
        body = {**json.loads(row["query"]), "operation": "summary",
                "from": datetime.fromtimestamp(now - row["window_minutes"] * 60, timezone.utc),
                "to": datetime.fromtimestamp(now, timezone.utc)}
        summary = queries.execute(store, QueryRequest.model_validate(body))["summary"]
    except (ValidationError, ValueError, KeyError, sqlite3.Error) as exc:
        logger.warning("stats_tripwire_query_failed", tripwire=row["id"], error_type=type(exc).__name__)
        return None
    value = summary["value"] if summary else None
    return float(value) if isinstance(value, (int, float)) else None


def _step(row: sqlite3.Row, value: float | None, now: int) -> dict:
    state, pending = row["state"], row["pending_since"]
    hold = row["for_minutes"] * 60
    if value is None:
        return {"state": "unknown", "since": now if state != "unknown" else row["since"],
                "pending_since": None, "transition": None}
    breach = value > row["threshold"] if row["comparator"] == ">" else value < row["threshold"]
    if state == "firing":
        if breach:
            return {"state": "firing", "since": row["since"], "pending_since": None, "transition": None}
        pending = now if pending is None else pending
        if now - pending >= hold:
            return {"state": "ok", "since": now, "pending_since": None, "transition": "ok"}
        return {"state": "firing", "since": row["since"], "pending_since": pending, "transition": None}
    if not breach:
        return {"state": "ok", "since": now if state != "ok" else row["since"],
                "pending_since": None, "transition": None}
    pending = now if pending is None else pending
    fired_at = row["last_fired_at"]
    cooled = fired_at is None or now - fired_at >= row["cooldown_minutes"] * 60
    if now - pending >= hold and cooled:
        return {"state": "firing", "since": now, "pending_since": None, "transition": "firing"}
    return {"state": state, "since": row["since"], "pending_since": pending, "transition": None}


def evaluate_all(store, now: float | None = None) -> list[dict]:
    stamp = time.time() if now is None else now
    with store.connect(readonly=True) as db:
        rows = db.execute("SELECT * FROM stats_tripwires WHERE enabled=1").fetchall()
    frames = []
    for row in rows:
        value = _measure(store, row, stamp)
        change = _step(row, value, int(stamp))
        fired = int(stamp) if change["transition"] == "firing" else row["last_fired_at"]
        with store.connect() as db:
            db.execute("UPDATE stats_tripwires SET state=?,since=?,pending_since=?,last_fired_at=?,"
                       "last_value=? WHERE id=? AND enabled=1",
                       (change["state"], change["since"], change["pending_since"], fired,
                        value if value is not None else row["last_value"], row["id"]))
        if change["transition"] is None:
            continue
        kind = "tripwire_fired" if change["transition"] == "firing" else "tripwire_resolved"
        events.record(kind, row["id"], {"value": value, "threshold": row["threshold"]},
                      store=store, occurred_at=int(stamp))
        frames.append({"type": "stats.tripwire", "id": row["id"], "name": row["name"],
                       "state": change["transition"], "value": value,
                       "threshold": row["threshold"], "comparator": row["comparator"]})
    return frames
