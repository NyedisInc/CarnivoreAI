
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from src.core.db import transaction
from src.core.pack.relay.target_side import relay_profile_name


@dataclass(frozen=True)
class Target:

    account_key: str
    target_install_id: str
    target_profile: str
    last_expiry_pushed: Optional[int]
    last_push_at: Optional[float]
    state: str

    @property
    def enabled(self) -> bool:
        return self.state != "off"


DEFAULT_MARK = "*"

_COLUMNS = "account_key, target_install_id, target_profile, last_expiry_pushed, last_push_at, state"


def list_all(conn: sqlite3.Connection) -> List[Target]:
    return [Target(*r) for r in conn.execute(
        f"SELECT {_COLUMNS} FROM pack_relay_targets WHERE target_install_id != ? "
        "ORDER BY account_key, target_install_id", (DEFAULT_MARK,))]


def enabled_for(conn: sqlite3.Connection, account_key: str) -> List[Target]:
    return [Target(*r) for r in conn.execute(
        f"SELECT {_COLUMNS} FROM pack_relay_targets WHERE account_key = ? AND state != 'off' AND target_install_id != ?",
        (account_key, DEFAULT_MARK))]


def default_mode(conn: sqlite3.Connection, account_key: str) -> bool:
    marks = [r[0] for r in conn.execute(
        "SELECT state FROM pack_relay_targets WHERE account_key = ? AND target_install_id = ?", (account_key, DEFAULT_MARK))]
    if marks:
        return marks[0] == "on"
    return conn.execute("SELECT 1 FROM pack_relay_targets WHERE account_key = ? LIMIT 1", (account_key,)).fetchone() is None


def effective_on(conn: sqlite3.Connection, account_key: str) -> bool:
    return default_mode(conn, account_key) or bool(enabled_for(conn, account_key))


def arm_default(conn: sqlite3.Connection, account_key: str, install_ids: Iterable[str], sender_install_id: str) -> None:
    with transaction(conn):
        if not default_mode(conn, account_key):
            return
        conn.execute("INSERT OR IGNORE INTO pack_relay_targets (account_key, target_install_id, target_profile, state) "
                     "VALUES (?, ?, '', 'on')", (account_key, DEFAULT_MARK))
        for iid in install_ids:
            conn.execute("INSERT OR IGNORE INTO pack_relay_targets (account_key, target_install_id, target_profile, state) "
                         "VALUES (?, ?, ?, 'on')", (account_key, iid, relay_profile_name(account_key, sender_install_id)))


def is_owner_of(conn: sqlite3.Connection, account_key: str) -> bool:
    return bool(enabled_for(conn, account_key))


def set_machines(conn: sqlite3.Connection, account_key: str, install_ids: Iterable[str], sender_install_id: str) -> List[str]:
    wanted = list(dict.fromkeys(install_ids))
    with transaction(conn):
        dropped = [r[0] for r in conn.execute(
            "SELECT target_install_id FROM pack_relay_targets WHERE account_key = ? AND state != 'off' "
            "AND target_install_id != ?", (account_key, DEFAULT_MARK)) if r[0] not in wanted]
        conn.execute("INSERT OR IGNORE INTO pack_relay_targets (account_key, target_install_id, target_profile, state) "
                     "VALUES (?, ?, '', 'off')", (account_key, DEFAULT_MARK))
        for iid in wanted:
            conn.execute(
                "INSERT INTO pack_relay_targets (account_key, target_install_id, target_profile, state) "
                "VALUES (?, ?, ?, 'on') ON CONFLICT(account_key, target_install_id) DO UPDATE SET state = "
                "CASE WHEN state IN ('off', 'refused') THEN 'on' ELSE state END",
                (account_key, iid, relay_profile_name(account_key, sender_install_id)))
        marks = ",".join("?" * len(wanted))
        conn.execute(
            "UPDATE pack_relay_targets SET state = 'off', last_expiry_pushed = NULL "
            f"WHERE account_key = ?{' AND target_install_id NOT IN (' + marks + ')' if wanted else ''}",
            (account_key, *wanted))
    return dropped


def record(conn: sqlite3.Connection, account_key: str, target_install_id: str, state: str,
           expiry_ms: Optional[int] = None, now: Optional[float] = None) -> None:
    with transaction(conn):
        if state == "pushed":
            conn.execute("UPDATE pack_relay_targets SET state = 'pushed', last_expiry_pushed = ?, last_push_at = ? "
                         "WHERE account_key = ? AND target_install_id = ? AND state != 'off'",
                         (expiry_ms, now if now is not None else time.time(), account_key, target_install_id))
        else:
            conn.execute("UPDATE pack_relay_targets SET state = ? WHERE account_key = ? AND target_install_id = ? "
                         "AND state != 'off'", (state, account_key, target_install_id))


def summary(conn: sqlite3.Connection) -> Dict[str, List[Dict[str, object]]]:
    out: Dict[str, List[Dict[str, object]]] = {}
    for t in list_all(conn):
        out.setdefault(t.account_key, []).append({
            "machine": t.target_install_id, "profile": t.target_profile, "state": t.state,
            "last_expiry_pushed": t.last_expiry_pushed, "last_push_at": t.last_push_at})
    return out
