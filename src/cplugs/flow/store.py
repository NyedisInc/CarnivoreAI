
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

from src.cplugs.sdk import CplugStorage

MIGRATIONS = (
    """
    CREATE TABLE snapshots (
        key          TEXT PRIMARY KEY,
        seed_kind    TEXT NOT NULL,
        seed_id      TEXT NOT NULL,
        window_start REAL NOT NULL,
        window_end   REAL NOT NULL,
        built_at     REAL NOT NULL,
        version      INTEGER NOT NULL,
        body         TEXT NOT NULL
    );
    CREATE INDEX snapshots_built ON snapshots (built_at);
    """,
)
KEEP = 100


def snapshot_key(kind: str, seed_id: str, start: Optional[float], end: Optional[float]) -> str:
    return f"{kind}:{seed_id}:{'' if start is None else start}:{'' if end is None else end}"


def load(storage: CplugStorage, key: str, version: int) -> Optional[Dict[str, Any]]:
    conn = storage.connect(False)
    try:
        row = conn.execute("SELECT body, built_at, version FROM snapshots WHERE key=?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if row is None or row[2] != version:
        return None
    run = json.loads(row[0])
    run["built_at"] = row[1]
    return run


def save(storage: CplugStorage, key: str, run: Dict[str, Any], built_at: float, version: int) -> None:
    conn = storage.connect(True)
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO snapshots (key, seed_kind, seed_id, window_start, window_end, built_at, version, body) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (key, run["seed"]["kind"], run["seed"]["id"], run["window"]["start"], run["window"]["end"], built_at, version,
                          json.dumps(run, separators=(",", ":"))))
            conn.execute("DELETE FROM snapshots WHERE key NOT IN (SELECT key FROM snapshots ORDER BY built_at DESC LIMIT ?)", (KEEP,))
    finally:
        conn.close()
