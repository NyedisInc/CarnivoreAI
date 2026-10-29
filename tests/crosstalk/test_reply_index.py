
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.crosstalk import receipt
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated

REPLY_INDEX = "ix_crosstalk_in_reply_to"
DUE_ROWS = 100
HISTORY = 20_000
VM_STEP = 100
INSERT = """INSERT INTO crosstalk_messages (id,thread,sender_key,receiver_key,sender_id,receiver_id,sender_name,
    sender_provider,text,in_reply_to,status,reason,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _plan_of_the_answered_check(conn: sqlite3.Connection) -> str:
    sql = f"SELECT id FROM crosstalk_messages WHERE {receipt.HELD_NATIVE} AND ({receipt.DUE_ANSWERED})"
    return " | ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, (0.0,)))


def test_the_answered_check_uses_the_reply_index(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with sqlite3.connect(db_path_for(tmp_path)) as conn:
        plan = _plan_of_the_answered_check(conn)
    assert f"USING COVERING INDEX {REPLY_INDEX}" in plan, plan


def _seed(conn: sqlite3.Connection, history: int) -> None:
    rows = [(f"due{i}", "t", "S", "R", "s", "r", "S", "claude", "x", None, "held",
             f"{receipt.PENDING_PREFIX}x", 1.0, 2.0) for i in range(DUE_ROWS)]
    rows += [(f"sent{i}", "t", "R", "S", "r", "s", "R", "claude", "x", f"other{i}" if i % 3 == 0 else None,
              "delivered", None, 1.0, 2.0) for i in range(history)]
    conn.executemany(INSERT, rows)
    conn.commit()


def _vm_steps_of_the_due_query(db: Path, history: int) -> int:
    with sqlite3.connect(db) as conn:
        _seed(conn, history)
        ticks = [0]

        def tick() -> int:
            ticks[0] += 1
            return 0

        conn.set_progress_handler(tick, VM_STEP)
        sql = f"SELECT 1 FROM crosstalk_messages WHERE id=? AND {receipt.ANSWERED}"
        for i in range(DUE_ROWS):
            assert conn.execute(sql, (f"due{i}",)).fetchall() == []
        conn.set_progress_handler(None, 0)
    return ticks[0]


def test_the_answered_check_does_not_grow_with_the_receivers_sent_history(tmp_path):
    small, large = tmp_path / "small", tmp_path / "large"
    small.mkdir(), large.mkdir()
    for state in (small, large):
        assert ensure_db_migrated(state).status == "ok"
    base = _vm_steps_of_the_due_query(db_path_for(small), HISTORY)
    scaled = _vm_steps_of_the_due_query(db_path_for(large), 4 * HISTORY)
    assert scaled < 2 * base, f"work grew {scaled / base:.1f}x for 4x the history"
