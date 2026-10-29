
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Set

from src.cplugs.sdk.storage import CplugStorage, StorageSpec

DB_NAME = "automations.db"
FOLDER_NAME = "automations"

MIGRATIONS = (
    """
    CREATE TABLE automations (
        automation_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL, cron TEXT NOT NULL, target TEXT NOT NULL, delivery TEXT NOT NULL,
        next_fire_at REAL, revision INTEGER NOT NULL, created_by TEXT NOT NULL, seed_key TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL);
    CREATE TABLE runs (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE,
        automation_id TEXT NOT NULL REFERENCES automations(automation_id) ON DELETE CASCADE,
        trigger TEXT NOT NULL, slot_at REAL, status TEXT NOT NULL, reason TEXT,
        skip_count INTEGER NOT NULL DEFAULT 0, first_slot_at REAL, last_slot_at REAL,
        started_at REAL, ended_at REAL, boot_id TEXT, cost_usd REAL, sessions TEXT, child TEXT,
        report TEXT, report_bytes INTEGER NOT NULL DEFAULT 0, error TEXT, notes TEXT, created_at REAL NOT NULL);
    CREATE INDEX runs_by_automation ON runs(automation_id, seq);
    CREATE TABLE run_sessions (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE, session_uuid TEXT NOT NULL,
        session_row_id INTEGER, member_index INTEGER, slept_at REAL, closed_at REAL,
        PRIMARY KEY (run_id, session_uuid));
    CREATE TABLE seed_tombstones (seed_key TEXT PRIMARY KEY, deleted_at REAL NOT NULL);
    """,
    """
    ALTER TABLE automations ADD COLUMN description TEXT NOT NULL DEFAULT '';
    ALTER TABLE automations ADD COLUMN project_id INTEGER;
    ALTER TABLE automations ADD COLUMN created_actor TEXT;
    ALTER TABLE automations ADD COLUMN updated_by TEXT NOT NULL DEFAULT 'app';
    ALTER TABLE automations ADD COLUMN updated_actor TEXT;
    ALTER TABLE automations ADD COLUMN misfire TEXT NOT NULL DEFAULT 'skip';
    ALTER TABLE automations ADD COLUMN retry_max INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE automations ADD COLUMN retry_backoff_s INTEGER NOT NULL DEFAULT 300;
    ALTER TABLE automations ADD COLUMN max_runtime_s INTEGER;
    ALTER TABLE automations ADD COLUMN retry_due_at REAL;
    ALTER TABLE automations ADD COLUMN retry_attempt INTEGER NOT NULL DEFAULT 0;
    UPDATE automations SET updated_by = created_by;
    ALTER TABLE runs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1;
    CREATE TABLE automation_changes (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, automation_id TEXT NOT NULL, action TEXT NOT NULL, at REAL NOT NULL,
        actor TEXT NOT NULL, before TEXT, after TEXT);
    CREATE INDEX changes_by_automation ON automation_changes(automation_id, seq);
    """,
    """
    ALTER TABLE runs ADD COLUMN number INTEGER;
    ALTER TABLE runs ADD COLUMN host TEXT;
    ALTER TABLE runs ADD COLUMN output_empty INTEGER;
    ALTER TABLE runs ADD COLUMN usage TEXT;
    ALTER TABLE runs ADD COLUMN delivered TEXT;
    ALTER TABLE runs ADD COLUMN attachments TEXT;
    UPDATE runs SET number = (SELECT COUNT(*) FROM runs r2 WHERE r2.automation_id = runs.automation_id AND r2.seq <= runs.seq);
    UPDATE runs SET output_empty = CASE WHEN EXISTS (
        SELECT 1 FROM json_tree(runs.report) t
        WHERE t.atom IS NOT NULL
          AND NOT (t.type = 'text' AND trim(t.atom, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)) = '')
          AND NOT EXISTS (SELECT 1 FROM (SELECT '$.command' AS k UNION ALL SELECT '$."command"' UNION ALL SELECT '$.exit_code'
                          UNION ALL SELECT '$."exit_code"' UNION ALL SELECT '$.duration_s' UNION ALL SELECT '$."duration_s"')
                          WHERE t.fullkey = k OR substr(t.fullkey, 1, length(k) + 1) IN (k || '.', k || '['))
      ) THEN 0 ELSE 1 END
      WHERE report IS NOT NULL AND json_valid(report) AND report != '{"pruned": true}';
    """,
    """
    ALTER TABLE runs ADD COLUMN title TEXT;
    ALTER TABLE runs ADD COLUMN summary TEXT;
    """,
)
STORAGE = StorageSpec(db=DB_NAME, migrations=MIGRATIONS)

JSON_RUN = ("sessions", "child", "report", "notes", "usage", "delivered", "attachments")


def next_number(tx: "Tx", automation_id: str) -> int:
    return tx.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM runs WHERE automation_id = ?", (automation_id,)).fetchone()[0]


def storage_for(state_dir: Path) -> CplugStorage:
    return CplugStorage(Path(state_dir) / FOLDER_NAME, STORAGE, Path(state_dir))


def automation_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {"automation_id": row["automation_id"], "name": row["name"], "enabled": bool(row["enabled"]),
            "trigger": {"cron": row["cron"], "timezone": "local"}, "target": json.loads(row["target"]),
            "delivery": json.loads(row["delivery"]), "next_fire_at": row["next_fire_at"], "revision": row["revision"],
            "created_by": row["created_by"], "seed_key": row["seed_key"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "description": row["description"], "project_id": row["project_id"],
            "created_actor": json.loads(row["created_actor"]) if row["created_actor"] else {"kind": row["created_by"]},
            "updated_by": row["updated_by"],
            "updated_actor": json.loads(row["updated_actor"]) if row["updated_actor"] else {"kind": row["updated_by"]},
            "misfire": row["misfire"], "retry_max": row["retry_max"], "retry_backoff_s": row["retry_backoff_s"],
            "max_runtime_s": row["max_runtime_s"], "retry_due_at": row["retry_due_at"]}


def run_row(row: sqlite3.Row) -> Dict[str, Any]:
    out = {k: row[k] for k in row.keys() if k not in ("seq", *JSON_RUN)}
    for key in JSON_RUN:
        out[key] = json.loads(row[key]) if row[key] else None
    out["output_empty"] = None if row["output_empty"] is None else bool(row["output_empty"])
    return out


class Tx:

    def __init__(self, conn: sqlite3.Connection, hit: Set[str]) -> None:
        self.conn = conn
        self.hit = hit

    def execute(self, sql: str, args: Any = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, args)


@contextmanager
def closing(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
    finally:
        conn.close()
