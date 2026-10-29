
from __future__ import annotations

import os
import sqlite3

from src.core.attention.codex_reader import CODEX_RECORD_ABSENT
from src.core.attention.codex_stores import _connect_ro, read_codex_record

THREAD = "ad166ca4-f8b4-989f-dee8-b5b4f34999e3"


def _make_wal_history_db(path):
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE thread_turns (thread_id TEXT NOT NULL, turn_id TEXT "
        "NOT NULL, rollout_ordinal INTEGER NOT NULL, status TEXT NOT NULL, "
        "error_json TEXT, started_at INTEGER, completed_at INTEGER, "
        "duration_ms INTEGER, first_user_item_id TEXT, final_agent_item_id "
        "TEXT, PRIMARY KEY (thread_id, turn_id))"
    )
    con.execute(
        "CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY "
        "KEY, next_rollout_byte_offset INTEGER NOT NULL, next_rollout_ordinal "
        "INTEGER NOT NULL)"
    )
    con.execute(
        "INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, "
        "status, error_json) VALUES (?, ?, ?, ?, ?)",
        (THREAD, "turn_0", 0, "completed", None),
    )
    con.execute(
        "INSERT INTO thread_history_projection_state VALUES (?, ?, ?)",
        (THREAD, 1000, 1),
    )
    con.commit()
    con.close()


def test_wal_format_db_with_no_wal_file_still_reads(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_wal_history_db(db)
    assert not os.path.exists(str(db) + "-wal")

    con = _connect_ro(db)
    assert con is not None
    try:
        row = con.execute(
            "SELECT status FROM thread_turns WHERE thread_id = ?", (THREAD,)
        ).fetchone()
    finally:
        con.close()
    assert row == ("completed",)


def test_wal_format_db_with_no_wal_file_creates_no_side_files(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_wal_history_db(db)
    assert sorted(os.listdir(tmp_path)) == ["thread_history_1.sqlite"]

    con = _connect_ro(db)
    assert con is not None
    con.execute("SELECT 1").fetchone()
    con.close()

    ro_only = "file:%s?mode=ro" % os.fspath(db)
    leaked = sqlite3.connect(ro_only, uri=True, timeout=0.5)
    leaked.execute("SELECT 1").fetchone()
    leaked.close()
    assert os.path.exists(str(db) + "-wal"), (
        "negative control did not reproduce: mode=ro no longer leaks a "
        "-wal file on this machine, so this test no longer proves anything"
    )

    db2 = tmp_path / "thread_history_2.sqlite"
    _make_wal_history_db(db2)
    con2 = _connect_ro(db2)
    con2.execute("SELECT 1").fetchone()
    con2.close()
    assert sorted(os.listdir(tmp_path)) == sorted(
        [
            "thread_history_1.sqlite",
            "thread_history_1.sqlite-wal",
            "thread_history_1.sqlite-shm",
            "thread_history_2.sqlite",
        ]
    )


def test_live_wal_file_still_opens_mode_ro(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    con = sqlite3.connect(str(db))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE thread_turns (thread_id TEXT, status TEXT)")
    con.execute("BEGIN")
    con.execute("INSERT INTO thread_turns VALUES (?, ?)", (THREAD, "inProgress"))
    con.commit()
    assert os.path.exists(str(db) + "-wal")

    read = _connect_ro(db)
    assert read is not None
    row = read.execute(
        "SELECT status FROM thread_turns WHERE thread_id = ?", (THREAD,)
    ).fetchone()
    read.close()
    con.close()
    assert row == ("inProgress",)


def test_read_codex_record_recovers_tier_with_no_wal_file(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_wal_history_db(db)
    assert not os.path.exists(str(db) + "-wal")

    facts = read_codex_record(db, THREAD, lock_live=False)
    assert facts.verdict != CODEX_RECORD_ABSENT


def test_connect_ro_on_missing_file_is_none_not_a_raise(tmp_path):
    assert _connect_ro(tmp_path / "nope.sqlite") is None
