
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.config import settings as app_settings
from src.core import db, resource_push
from src.core.resource_push import topics

FILE_NAME = "argent.db"

MIGRATIONS: Tuple[str, ...] = (
    """
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE login (
        tenant_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, display_name TEXT NOT NULL,
        expires_at REAL NOT NULL, updated_at REAL NOT NULL);
    """,
    """
    CREATE TABLE work_items (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, parent_id TEXT, title TEXT NOT NULL, status TEXT NOT NULL,
        merged_into TEXT, updated_at TEXT NOT NULL, raw TEXT NOT NULL, PRIMARY KEY (tenant_id, id));
    CREATE INDEX work_items_parent ON work_items (tenant_id, parent_id);
    """,
    """
    CREATE TABLE row_state (
        tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, working_dir TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '', pending_state TEXT NOT NULL DEFAULT '', pending_reason TEXT NOT NULL DEFAULT '',
        notified INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL, PRIMARY KEY (tenant_id, session_ref));
    CREATE TABLE row_keys (
        tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, key_id TEXT NOT NULL, status TEXT NOT NULL, minted_at REAL NOT NULL,
        PRIMARY KEY (tenant_id, session_ref, key_id))
    """,
    """
    CREATE TABLE ref_alias (
        tenant_id TEXT NOT NULL, tmux_name TEXT NOT NULL, session_ref TEXT NOT NULL, session_uuid TEXT NOT NULL DEFAULT '',
        agent_id TEXT NOT NULL DEFAULT '', reg TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL, PRIMARY KEY (tenant_id, tmux_name));
    CREATE INDEX ref_alias_uuid ON ref_alias (tenant_id, session_uuid)
    """,
    """
    CREATE TABLE timeline_queue (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, sub_agent_id TEXT NOT NULL,
        work_item_id TEXT NOT NULL, ts TEXT NOT NULL, reason TEXT NOT NULL, acked_at REAL);
    CREATE INDEX timeline_queue_tenant ON timeline_queue (tenant_id, acked_at, seq);
    CREATE TABLE timeline_current (
        tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, sub_agent_id TEXT NOT NULL, work_item_id TEXT NOT NULL, ts TEXT NOT NULL,
        reason TEXT NOT NULL, PRIMARY KEY (tenant_id, session_ref, sub_agent_id))
    """,
    """
    CREATE TABLE rollout (
        tenant_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, direction TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
        started_at REAL NOT NULL, updated_at REAL NOT NULL);
    CREATE TABLE rollout_rows (
        tenant_id TEXT NOT NULL, epoch INTEGER NOT NULL, tmux_name TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
        first_seen REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (tenant_id, epoch, tmux_name))
    """,
    """
    CREATE TABLE budget_level (
        tenant_id TEXT NOT NULL, item_id TEXT NOT NULL, level TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (tenant_id, item_id))
    """,
    """
    CREATE TABLE commits (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, sha TEXT NOT NULL, sub_agent_id TEXT NOT NULL,
        source TEXT NOT NULL, subject TEXT NOT NULL, files TEXT NOT NULL, file_count INTEGER NOT NULL, detected_at REAL NOT NULL,
        UNIQUE (tenant_id, session_ref, sha));
    CREATE TABLE commit_cursor (
        tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (tenant_id, session_ref, key))
    """,
    """
    CREATE TABLE retether (
        tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, last_at REAL NOT NULL, reason TEXT NOT NULL DEFAULT '', PRIMARY KEY (tenant_id, session_ref))
    """,
    """
    CREATE TABLE writeback (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, session_ref TEXT NOT NULL, tmux_name TEXT NOT NULL, session_name TEXT NOT NULL DEFAULT '',
        item_id TEXT NOT NULL, milestone TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', body TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL, due_at REAL NOT NULL, composed_at REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
        next_try REAL NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '');
    CREATE INDEX writeback_state ON writeback (tenant_id, state, id)
    """,
    """
    ALTER TABLE row_keys ADD COLUMN key_expires_at REAL NOT NULL DEFAULT 0
    """,
)


def path_in(state_dir: Path) -> Path:
    return state_dir / FILE_NAME


def _open(state_dir: Optional[Path] = None) -> sqlite3.Connection:
    conn = db.connect(path_in(state_dir or app_settings.get_state_dir()), create=True)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        have = int(row[0] or 0)
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= have:
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in filter(None, (s.strip() for s in script.split(";"))):
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def open_db(state_dir: Optional[Path] = None) -> sqlite3.Connection:
    return _open(state_dir)


LOGIN_SOON_SECONDS = 30 * 60


class ArgentStore:

    def __init__(self, state_dir: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
        self._state_dir = state_dir
        self._clock = clock

    def _meta(self, conn: sqlite3.Connection, key: str) -> Optional[str]:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def _put_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def get_login(self) -> Optional[Dict[str, object]]:
        with closing(_open(self._state_dir)) as conn:
            tenant = self._meta(conn, "tenant_id")
            row = conn.execute("SELECT tenant_id, identity_id, display_name, expires_at FROM login WHERE tenant_id = ?", (tenant,)).fetchone() if tenant else None
            return dict(row) if row else None

    def set_login(self, tenant_id: str, identity_id: str, display_name: str, expires_in: int, source: str = "own") -> Optional[str]:
        now = self._clock()
        with closing(_open(self._state_dir)) as conn:
            previous = self._meta(conn, "tenant_id")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO login (tenant_id, identity_id, display_name, expires_at, updated_at) VALUES (?, ?, ?, ?, ?) "
                         "ON CONFLICT(tenant_id) DO UPDATE SET identity_id = excluded.identity_id, display_name = excluded.display_name, "
                         "expires_at = excluded.expires_at, updated_at = excluded.updated_at",
                         (tenant_id, identity_id, display_name, now + max(0, int(expires_in)), now))
            self._put_meta(conn, "tenant_id", tenant_id)
            self._put_meta(conn, "login_expired", "0")
            self._put_meta(conn, "login_source", source)
            conn.execute("COMMIT")
        return previous if previous and previous != tenant_id else None

    def clear_login(self) -> None:
        with closing(_open(self._state_dir)) as conn:
            tenant = self._meta(conn, "tenant_id")
            conn.execute("BEGIN IMMEDIATE")
            if tenant:
                conn.execute("DELETE FROM login WHERE tenant_id = ?", (tenant,))
            conn.execute("DELETE FROM meta WHERE key IN ('tenant_id', 'login_expired', 'login_source')")
            conn.execute("COMMIT")

    def login_expired(self) -> bool:
        with closing(_open(self._state_dir)) as conn:
            return self._meta(conn, "login_expired") == "1"

    def mark_login_expired(self) -> None:
        with closing(_open(self._state_dir)) as conn:
            relayed = (self._meta(conn, "login_source") or "own").startswith("relay:")
            if not relayed:
                changed = self._meta(conn, "login_expired") != "1"
                self._put_meta(conn, "login_expired", "1")
        if relayed:
            from src.core.argent import pair_sync  # noqa: PLC0415

            pair_sync.copy_unauthorized()
            return
        if changed:
            resource_push.notify(topics.ARGENT_STATUS)

    def login_phase(self) -> str:
        row = self.get_login()
        if row is None:
            return "out"
        left = float(row["expires_at"]) - self._clock()
        return "expired" if self.login_expired() or left <= 0 else ("soon" if left <= LOGIN_SOON_SECONDS else "ok")

    def delegate_get(self, install_id: str) -> Optional[Dict[str, Any]]:
        with closing(_open(self._state_dir)) as conn:
            raw = self._meta(conn, f"delegate:{install_id}")
        return json.loads(raw) if raw else None

    def delegate_put(self, install_id: str, record: Dict[str, Any]) -> None:
        with closing(_open(self._state_dir)) as conn:
            self._put_meta(conn, f"delegate:{install_id}", json.dumps(record))

    def delegate_drop(self, install_id: str) -> None:
        with closing(_open(self._state_dir)) as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", (f"delegate:{install_id}",))

    def delegate_installs(self) -> List[str]:
        with closing(_open(self._state_dir)) as conn:
            return [str(r[0])[9:] for r in conn.execute("SELECT key FROM meta WHERE key LIKE 'delegate:%'")]

    def login_source_recorded(self) -> str:
        with closing(_open(self._state_dir)) as conn:
            return self._meta(conn, "login_source") or ""

    def login_issued_at(self) -> float:
        with closing(_open(self._state_dir)) as conn:
            tenant = self._meta(conn, "tenant_id")
            row = conn.execute("SELECT updated_at FROM login WHERE tenant_id = ?", (tenant,)).fetchone() if tenant else None
            return float(row[0]) if row else 0.0

    def login_source(self) -> str:
        with closing(_open(self._state_dir)) as conn:
            return self._meta(conn, "login_source") or "own"

    def pair_state(self) -> Tuple[int, str]:
        with closing(_open(self._state_dir)) as conn:
            return int(self._meta(conn, "pair_clock") or 0), self._meta(conn, "pair_origin") or ""

    def set_pair_state(self, clock: int, origin: str) -> None:
        with closing(_open(self._state_dir)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._put_meta(conn, "pair_clock", str(int(clock)))
            self._put_meta(conn, "pair_origin", origin)
            conn.execute("COMMIT")
