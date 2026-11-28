
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from typing import Callable, Dict, Iterable, List

YES, NO = "yes", "no"
_DDL = """CREATE TABLE IF NOT EXISTS pack_relay_approval (
    install_id  TEXT PRIMARY KEY,
    answer      TEXT NOT NULL CHECK (answer IN ('yes', 'no')),
    answered_at REAL NOT NULL
)"""


def ensure(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pack_relay_approval'").fetchone():
        return
    conn.execute(_DDL)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pack_relay_targets'").fetchone():
        conn.execute("INSERT OR IGNORE INTO pack_relay_approval SELECT DISTINCT target_install_id, 'yes', ? "
                     "FROM pack_relay_targets WHERE state != 'off' AND target_install_id != ''", (time.time(),))
    conn.commit()


def answers(conn: sqlite3.Connection) -> Dict[str, str]:
    ensure(conn)
    return {r[0]: r[1] for r in conn.execute("SELECT install_id, answer FROM pack_relay_approval")}


def forget(conn: sqlite3.Connection, install_id: str) -> bool:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pack_relay_approval'").fetchone():
        return False
    gone = conn.execute("DELETE FROM pack_relay_approval WHERE install_id = ?", (install_id,)).rowcount > 0
    conn.commit()
    return gone


def pending(recorded: Dict[str, str], candidates: Iterable[str]) -> List[str]:
    return [iid for iid in candidates if iid not in recorded]


def record(conn: sqlite3.Connection, install_id: str, answer: str) -> None:
    if answer not in (YES, NO):
        raise ValueError("bad_answer")
    ensure(conn)
    conn.execute("INSERT INTO pack_relay_approval (install_id, answer, answered_at) VALUES (?, ?, ?) "
                 "ON CONFLICT(install_id) DO UPDATE SET answer = excluded.answer, answered_at = excluded.answered_at",
                 (install_id, answer, time.time()))
    conn.commit()


def reader(open_db: Callable[[], sqlite3.Connection]) -> Callable[[str], bool]:
    def approved(install_id: str) -> bool:
        with closing(open_db()) as conn:
            return answers(conn).get(install_id) == YES
    return approved
