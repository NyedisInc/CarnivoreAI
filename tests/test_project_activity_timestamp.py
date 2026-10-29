
from __future__ import annotations

import sqlite3

import pytest

from src.core.message_activity import (
    ACTIVITY_KNOWN,
    ACTIVITY_NONE,
    ACTIVITY_UNKNOWN,
    backfill_transcript_activity,
    classify_activity,
    install_transcript_activity,
    merge_activity,
    newest_ts_for_bodies,
)


def _bodies_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE message_transcripts (
            id INTEGER PRIMARY KEY, newest_message_ts TEXT);
        CREATE TABLE message_bodies (id INTEGER PRIMARY KEY, ts TEXT);
        CREATE TABLE message_appearances (
            id INTEGER PRIMARY KEY, transcript_id INTEGER, body_id INTEGER);
        INSERT INTO message_transcripts (id) VALUES (1), (2), (3);
        INSERT INTO message_bodies VALUES
            (10, '2026-01-01T00:00:00Z'),
            (11, '2026-08-30T00:00:00Z'),
            (12, NULL);
        INSERT INTO message_appearances VALUES
            (1, 1, 10), (2, 1, 11),
            (3, 2, 12),
            (4, 3, NULL);
        """
    )
    return conn


def test_the_backfill_writes_the_nulls_too():
    conn = _bodies_conn()
    written = backfill_transcript_activity(conn)
    assert written == 3, "every transcript is written, including the NULLs"
    got = {
        r["id"]: r["newest_message_ts"]
        for r in conn.execute("SELECT id, newest_message_ts FROM message_transcripts")
    }
    assert got[1] == "2026-08-30T00:00:00Z", "the MAX, not the first"
    assert got[2] is None, "its only body carries no ts"
    assert got[3] is None, "it has no body at all"


def test_the_backfill_is_idempotent():
    conn = _bodies_conn()
    backfill_transcript_activity(conn)
    first = conn.execute(
        "SELECT id, newest_message_ts FROM message_transcripts ORDER BY id"
    ).fetchall()
    backfill_transcript_activity(conn)
    second = conn.execute(
        "SELECT id, newest_message_ts FROM message_transcripts ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in first] == [tuple(r) for r in second]


def test_the_ingest_lookup_and_the_backfill_agree():
    conn = _bodies_conn()
    backfill_transcript_activity(conn)
    for tid in (1, 2, 3):
        ids = [
            r[0] for r in conn.execute(
                "SELECT body_id FROM message_appearances WHERE transcript_id = ?",
                (tid,),
            )
        ]
        stored = conn.execute(
            "SELECT newest_message_ts FROM message_transcripts WHERE id = ?",
            (tid,),
        ).fetchone()[0]
        assert newest_ts_for_bodies(conn, ids) == stored


def test_the_ingest_lookup_survives_more_ids_than_sqlite_binds():
    conn = _bodies_conn()
    many = []
    for i in range(2000):
        conn.execute(
            "INSERT INTO message_bodies VALUES (?, ?)",
            (1000 + i, f"2026-02-{(i % 27) + 1:02d}T00:00:00Z"),
        )
        many.append(1000 + i)
    assert newest_ts_for_bodies(conn, many) == "2026-02-27T00:00:00Z"


def test_installing_on_an_archive_less_database_is_a_no_op_not_a_crash():
    conn = sqlite3.connect(":memory:")
    assert install_transcript_activity(conn) is None


def test_installing_twice_does_not_raise_on_the_second_add_column():
    conn = _bodies_conn()
    conn.execute("ALTER TABLE message_transcripts DROP COLUMN newest_message_ts")
    assert install_transcript_activity(conn) == 3
    assert install_transcript_activity(conn) == 3
