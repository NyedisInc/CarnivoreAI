
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.messaging import ddl

MAY = "may have been sent; do not resend"
ROWS = [
    ("m_uncertain_out", "out", "message", "failed", f"{MAY}: Restarted mid-send."),
    ("m_uncertain_bare", "out", "message", "failed", MAY),
    ("m_plain_fail", "out", "message", "failed", "That chat is protected."),
    ("m_inbound_fail", "in", "message", "failed", "delivery_uncertain"),
    ("m_sent", "out", "message", "delivered", None),
    ("m_held", "in", "message", "held", "dialog_open"),
]


def _v91(state_dir: Path) -> Path:
    path = db_path_for(state_dir)
    with closing(connect(path)) as conn:
        with conn:
            run_chain(conn, 0, 91)
            conn.execute("INSERT INTO messaging_providers (id, name, created_at, updated_at) VALUES ('p_1', 'imsg', 1, 1)")
            for n, (rid, direction, kind, status, reason) in enumerate(ROWS):
                conn.execute(
                    "INSERT INTO messaging_messages (id, provider_id, direction, kind, received_at, text, status, reason, "
                    "binding_id, provider_message_id, session_uuid, batch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, "p_1", direction, kind, 100.0 + n, f"text {n}", status, reason, f"b_{n}", f"pm_{n}", f"u_{n}", "t_1"))
    return path


def _rows(path: Path) -> dict:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return {r["id"]: dict(r) for r in conn.execute("SELECT * FROM messaging_messages")}


def test_the_migrator_backs_up_first_then_rebuilds_and_converts(tmp_path: Path) -> None:
    path = _v91(tmp_path)
    before = _rows(path)
    state = ensure_db_migrated(tmp_path)
    assert state.status == "ok" and CURRENT_SCHEMA_VERSION >= 96
    [backup] = list(tmp_path.glob("*.bak-v91-*"))
    assert _rows(backup)["m_uncertain_out"]["status"] == "failed"
    with closing(sqlite3.connect(backup)) as conn:
        assert "unconfirmed" not in conn.execute("SELECT sql FROM sqlite_master WHERE name = 'messaging_messages'").fetchone()[0]

    after = _rows(path)
    assert set(after) == set(before)
    for rid, row in before.items():
        expected = dict(row, status="unconfirmed") if rid in ("m_uncertain_out", "m_uncertain_bare") else row
        assert after[rid] == expected, rid
    assert after["m_plain_fail"]["status"] == "failed" and after["m_inbound_fail"]["status"] == "failed"


def test_the_rebuilt_table_enforces_the_new_check_and_keeps_its_indexes(tmp_path: Path) -> None:
    path = _v91(tmp_path)
    ensure_db_migrated(tmp_path)
    with closing(connect(path)) as conn:
        insert = ("INSERT INTO messaging_messages (id, provider_id, direction, kind, received_at, text, status) "
                  "VALUES (?, 'p_1', 'out', 'message', 1, 't', ?)")
        conn.execute(insert, ("m_new", "unconfirmed"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("m_bad", "maybe"))
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messaging_messages'")}
        assert {"ux_messaging_inbound_once", "ix_messaging_pending", "ix_messaging_out_reply", "ix_messaging_time"} <= indexes
        assert "replay_proven_at" in {r[1] for r in conn.execute("PRAGMA table_info(messaging_providers)")}
        assert conn.execute("SELECT replay_proven_at FROM messaging_providers WHERE id = 'p_1'").fetchone()[0] is None
        assert not [r for r in conn.execute("PRAGMA foreign_key_check")]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'messaging_messages_v92'").fetchone() is None


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    path = _v91(tmp_path)
    ensure_db_migrated(tmp_path)
    rows, files = _rows(path), sorted(p.name for p in tmp_path.iterdir())
    state = ensure_db_migrated(tmp_path)
    assert state.status == "ok" and state.migrations_applied == []
    assert _rows(path) == rows and sorted(p.name for p in tmp_path.iterdir()) == files


def test_apply_v92_alone_is_idempotent_and_a_fresh_database_ends_the_same() -> None:
    conn = sqlite3.connect(":memory:")
    run_chain(conn, 0, 91)
    ddl.apply_v92(conn)
    master = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'messaging_messages'").fetchone()[0]
    ddl.apply_v92(conn)
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'messaging_messages'").fetchone()[0] == master
    fresh = sqlite3.connect(":memory:")
    run_chain(fresh, 0, 92)
    assert fresh.execute("SELECT sql FROM sqlite_master WHERE name = 'messaging_messages'").fetchone()[0] == master
