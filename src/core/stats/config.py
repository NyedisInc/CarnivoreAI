from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from src.core.stats.plugin import usage_revision
from src.models.stats import AnnotationWrite, ChartWrite


class RevisionConflict(ValueError):
    pass


class NotFound(LookupError):
    pass


class StatsOff(RuntimeError):
    pass


def require_enabled(store) -> None:
    if not get_settings(store)["enabled"]:
        raise StatsOff("stats off")


def _bump(db) -> None:
    db.execute("UPDATE stats_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
    usage_revision.bump(db)


def ensure_schema(store) -> None:
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS stats_settings (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            revision INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stats_charts (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
            config_json TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stats_annotations (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
            occurred_at INTEGER NOT NULL, kind TEXT NOT NULL,
            label TEXT NOT NULL, scope_json TEXT NOT NULL,
            rule_hash TEXT, reference TEXT, basis TEXT NOT NULL,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_stats_annotations_time ON stats_annotations(occurred_at, id);
        CREATE TABLE IF NOT EXISTS stats_backfill (
            idempotency_key TEXT PRIMARY KEY, requested_at INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('requested','running','complete','failed')),
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stats_disabled_spans (
            start_ts INTEGER PRIMARY KEY, end_ts INTEGER
        );
        CREATE TABLE IF NOT EXISTS stats_tripwires (
            id TEXT PRIMARY KEY, chart_id TEXT, name TEXT NOT NULL,
            query TEXT NOT NULL, window_minutes INTEGER NOT NULL,
            comparator TEXT NOT NULL CHECK(comparator IN ('>','<')),
            threshold REAL NOT NULL, for_minutes INTEGER NOT NULL,
            cooldown_minutes INTEGER NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            state TEXT NOT NULL DEFAULT 'unknown' CHECK(state IN ('ok','firing','unknown')),
            since INTEGER NOT NULL, pending_since INTEGER, last_fired_at INTEGER,
            last_value REAL, created_at INTEGER NOT NULL
        );
        """)
        db.execute("INSERT OR IGNORE INTO stats_settings VALUES (1,?,1)",
                   (0 if os.environ.get("CLOUDE_TEST_MODE", "").lower() in ("1", "true", "yes") else 1,))
        _migrate_legend_on(db)


LEGEND_MIGRATION_KEY = "migration_legend_on_v1"


def _migrate_legend_on(db) -> None:
    db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT 1 FROM stats_meta WHERE key=?", (LEGEND_MIGRATION_KEY,)).fetchone():
            return
        changed = 0
        for row in db.execute("SELECT id, config_json FROM stats_charts").fetchall():
            stored = json.loads(row["config_json"])
            display = stored.get("display")
            if isinstance(display, dict) and display.get("legend") is False:
                display["legend"] = True
                db.execute("UPDATE stats_charts SET revision=revision+1, config_json=?, updated_at=? WHERE id=?",
                           (json.dumps(stored), int(time.time()), row["id"]))
                changed += 1
        db.execute("INSERT INTO stats_meta(key,value) VALUES (?,?)", (LEGEND_MIGRATION_KEY, str(changed)))
        if changed:
            _bump(db)
    finally:
        db.execute("COMMIT")


def get_settings(store) -> dict:
    with store.connect_read() as db:
        row = db.execute("SELECT enabled,revision FROM stats_settings WHERE singleton=1").fetchone()
    return {"enabled": bool(row["enabled"]), "revision": row["revision"]}


def update_settings(store, *, enabled: bool, revision: int) -> dict:
    with store.connect() as db:
        previous = db.execute("SELECT enabled FROM stats_settings WHERE singleton=1 AND revision=?",
                              (revision,)).fetchone()
        if previous is None:
            raise RevisionConflict("settings revision changed")
        cursor = db.execute(
            "UPDATE stats_settings SET enabled=?,revision=revision+1 WHERE singleton=1 AND revision=?",
            (int(enabled), revision),
        )
        if cursor.rowcount != 1:
            raise RevisionConflict("settings revision changed")
        if bool(previous["enabled"]) != enabled:
            wall = int(time.time())
            start_minute = wall // 60 * 60
            end_minute = (wall + 59) // 60 * 60
            if enabled:
                db.execute("UPDATE stats_disabled_spans SET end_ts=max(start_ts+60,?) "
                           "WHERE end_ts IS NULL", (end_minute,))
            else:
                db.execute("INSERT OR IGNORE INTO stats_disabled_spans VALUES (?,NULL)", (start_minute,))
        _bump(db)
    return get_settings(store)


def _chart(row) -> dict:
    stored = json.loads(row["config_json"])
    stored.setdefault("viz", "timeline")
    stored.setdefault("options", {})
    return {"id": row["id"], "revision": row["revision"], **stored,
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_charts(store) -> list[dict]:
    with store.connect(readonly=True) as db:
        rows = db.execute("SELECT * FROM stats_charts ORDER BY created_at,id LIMIT 200").fetchall()
    return [_chart(row) for row in rows]


def get_chart(store, chart_id: str) -> dict:
    with store.connect(readonly=True) as db:
        row = db.execute("SELECT * FROM stats_charts WHERE id=?", (chart_id,)).fetchone()
    if row is None:
        raise NotFound("chart")
    return _chart(row)


def create_chart(store, config: ChartWrite) -> dict:
    now = int(time.time())
    chart_id = str(config.id or uuid.uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM stats_charts").fetchone()[0] >= 200:
            raise ValueError("chart limit reached")
        db.execute("INSERT INTO stats_charts VALUES (?,?,?,?,?)",
                   (chart_id, 1, config.model_dump_json(by_alias=True, exclude={"id"}), now, now))
        _bump(db)
    return get_chart(store, chart_id)


def update_chart(store, chart_id: str, config: ChartWrite, revision: int) -> dict:
    with store.connect() as db:
        cursor = db.execute(
            "UPDATE stats_charts SET revision=revision+1,config_json=?,updated_at=? WHERE id=? AND revision=?",
            (config.model_dump_json(by_alias=True, exclude={"id", "revision"}), int(time.time()), chart_id, revision),
        )
        if cursor.rowcount != 1:
            if db.execute("SELECT 1 FROM stats_charts WHERE id=?", (chart_id,)).fetchone() is None:
                raise NotFound("chart")
            raise RevisionConflict("chart revision changed")
        _bump(db)
    return get_chart(store, chart_id)


def delete_chart(store, chart_id: str, revision: int) -> None:
    with store.connect() as db:
        cursor = db.execute("DELETE FROM stats_charts WHERE id=? AND revision=?", (chart_id, revision))
        if cursor.rowcount != 1:
            if db.execute("SELECT 1 FROM stats_charts WHERE id=?", (chart_id,)).fetchone() is None:
                raise NotFound("chart")
            raise RevisionConflict("chart revision changed")
        db.execute("DELETE FROM stats_tripwires WHERE chart_id=?", (chart_id,))
        _bump(db)


def _annotation(row) -> dict:
    return {key: row[key] for key in ("id", "revision", "occurred_at", "kind", "label",
                                     "rule_hash", "reference", "basis", "created_at", "updated_at")} | {
        "scope": json.loads(row["scope_json"])
    }


def list_annotations(store, *, start: int, end: int, limit: int = 200, cursor: int = 0,
                     filters=None) -> dict:
    where = ["occurred_at>=?", "occurred_at<?"]
    args = [start, end]
    if filters is not None:
        for key, value in filters.model_dump(exclude_none=True).items():
            where.append(f"(json_extract(scope_json,'$.{key}') IS NULL OR "
                         f"json_extract(scope_json,'$.{key}')=?)")
            args.append(value)
    with store.connect_read() as db:
        rows = db.execute(
            "SELECT * FROM stats_annotations WHERE " + " AND ".join(where) + " "
            "ORDER BY occurred_at,id LIMIT ? OFFSET ?",
            (*args, limit + 1, cursor),
        ).fetchall()
    return {"items": [_annotation(row) for row in rows[:limit]],
            "next_cursor": cursor + limit if len(rows) > limit else None}


def get_annotation(store, annotation_id: str) -> dict:
    with store.connect(readonly=True) as db:
        row = db.execute("SELECT * FROM stats_annotations WHERE id=?", (annotation_id,)).fetchone()
    if row is None:
        raise NotFound("annotation")
    return _annotation(row)


def create_annotation(store, value: AnnotationWrite) -> dict:
    now = int(time.time())
    annotation_id = str(uuid.uuid4())
    with store.connect() as db:
        db.execute("INSERT INTO stats_annotations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (annotation_id, 1, int(value.occurred_at.timestamp()), value.kind, value.label,
                    value.scope.model_dump_json(exclude_none=True), value.rule_hash,
                    value.reference, value.basis, now, now))
        _bump(db)
    return get_annotation(store, annotation_id)


def update_annotation(store, annotation_id: str, value: AnnotationWrite, revision: int) -> dict:
    with store.connect() as db:
        cursor = db.execute(
            "UPDATE stats_annotations SET revision=revision+1,occurred_at=?,kind=?,label=?,"
            "scope_json=?,rule_hash=?,reference=?,basis=?,updated_at=? WHERE id=? AND revision=?",
            (int(value.occurred_at.timestamp()), value.kind, value.label,
             value.scope.model_dump_json(exclude_none=True), value.rule_hash,
             value.reference, value.basis,
             int(time.time()), annotation_id, revision),
        )
        if cursor.rowcount != 1:
            if db.execute("SELECT 1 FROM stats_annotations WHERE id=?", (annotation_id,)).fetchone() is None:
                raise NotFound("annotation")
            raise RevisionConflict("annotation revision changed")
        _bump(db)
    return get_annotation(store, annotation_id)


def delete_annotation(store, annotation_id: str, revision: int) -> None:
    with store.connect() as db:
        cursor = db.execute("DELETE FROM stats_annotations WHERE id=? AND revision=?", (annotation_id, revision))
        if cursor.rowcount != 1:
            if db.execute("SELECT 1 FROM stats_annotations WHERE id=?", (annotation_id,)).fetchone() is None:
                raise NotFound("annotation")
            raise RevisionConflict("annotation revision changed")
        _bump(db)


def add_observed_annotation(store, *, kind: str, occurred_at: int, label: str,
                            scope: dict, rule_hash: str | None = None,
                            reference: str | None = None,
                            basis: str = "observed", connection=None) -> dict:
    from datetime import datetime, timezone
    value = AnnotationWrite(occurred_at=datetime.fromtimestamp(occurred_at, timezone.utc),
                            kind=kind, label=label, scope=scope, rule_hash=rule_hash,
                            reference=reference, basis=basis)
    if connection is not None:
        now = int(time.time())
        annotation_id = str(uuid.uuid4())
        connection.execute("INSERT INTO stats_annotations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (annotation_id, 1, occurred_at, value.kind, value.label,
                            value.scope.model_dump_json(exclude_none=True), value.rule_hash,
                            value.reference, value.basis, now, now))
        _bump(connection)
        return {"id": annotation_id, "revision": 1, "occurred_at": occurred_at,
                "kind": value.kind, "label": value.label, "scope": value.scope.model_dump(exclude_none=True),
                "rule_hash": value.rule_hash, "reference": value.reference,
                "basis": value.basis, "created_at": now, "updated_at": now}
    return create_annotation(store, value)


def request_backfill(store, key: str) -> dict:
    now = int(time.time())
    with store.connect() as db:
        db.execute("INSERT OR IGNORE INTO stats_backfill VALUES (?,?,'requested',?)", (key, now, now))
        row = db.execute("SELECT * FROM stats_backfill WHERE idempotency_key=?", (key,)).fetchone()
    return dict(row)


def update_backfill(store, key: str, state: str) -> None:
    if state not in ("requested", "running", "complete", "failed"):
        raise ValueError("invalid backfill state")
    with store.connect() as db:
        db.execute("UPDATE stats_backfill SET state=?,updated_at=? WHERE idempotency_key=?",
                   (state, int(time.time()), key))
