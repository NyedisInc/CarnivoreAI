
from __future__ import annotations

import sqlite3
from src.core.db import table_exists
from typing import Optional

_GROUPED_ACTIVITY_SQL = """
SELECT a.transcript_id AS transcript_id, MAX(b.ts) AS newest
  FROM message_appearances a
  JOIN message_bodies b ON b.id = a.body_id
 WHERE b.ts IS NOT NULL
 GROUP BY a.transcript_id
"""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = (table_exists(conn, table) or None)
    return row is not None


def has_activity_column(conn: sqlite3.Connection) -> bool:
    if not _table_exists(conn, "message_transcripts"):
        return False
    return any(
        row[1] == "newest_message_ts"
        for row in conn.execute("PRAGMA table_info(message_transcripts)")
    )


def install_transcript_activity(conn: sqlite3.Connection) -> Optional[int]:
    if not _table_exists(conn, "message_transcripts"):
        return None
    if not has_activity_column(conn):
        conn.execute(
            "ALTER TABLE message_transcripts ADD COLUMN newest_message_ts TEXT"
        )
    return backfill_transcript_activity(conn)


def backfill_transcript_activity(conn: sqlite3.Connection) -> int:
    conn.execute("DROP TABLE IF EXISTS temp.transcript_activity")
    conn.execute(
        "CREATE TEMP TABLE transcript_activity AS " + _GROUPED_ACTIVITY_SQL
    )
    conn.execute(
        "CREATE INDEX temp.ix_transcript_activity "
        "ON transcript_activity (transcript_id)"
    )
    cur = conn.execute(
        "UPDATE message_transcripts SET newest_message_ts = ("
        "  SELECT newest FROM temp.transcript_activity"
        "   WHERE transcript_id = message_transcripts.id)"
    )
    written = int(cur.rowcount if cur.rowcount is not None else 0)
    conn.execute("DROP TABLE IF EXISTS temp.transcript_activity")
    return written
