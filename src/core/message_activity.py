
from __future__ import annotations

import sqlite3
from src.core.db import table_exists
from typing import Any, Dict, Iterable, List, Optional, Sequence

ACTIVITY_KNOWN = "known"

ACTIVITY_NONE = "none"

# could not
ACTIVITY_UNKNOWN = "unknown"

ACTIVITY_STATUSES = (ACTIVITY_KNOWN, ACTIVITY_NONE, ACTIVITY_UNKNOWN)

ACTIVITY_MEANS = (
    "newest_activity_at is the newest message timestamp inside the "
    "project - when the owner was last working in it, NOT when this tool "
    "collected the files. activity_status is 'known' when that produced "
    "a timestamp, 'none' when the project's messages were read and none "
    "carried one, and 'unknown' when the database could not answer at "
    "all. 'none' and 'unknown' are different facts and must not be "
    "sorted as though they were the same."
)

_GROUPED_ACTIVITY_SQL = """
SELECT a.transcript_id AS transcript_id, MAX(b.ts) AS newest
  FROM message_appearances a
  JOIN message_bodies b ON b.id = a.body_id
 WHERE b.ts IS NOT NULL
 GROUP BY a.transcript_id
"""

_ID_CHUNK = 500


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


def newest_ts_for_bodies(
    conn: sqlite3.Connection, body_ids: Iterable[Optional[int]]
) -> Optional[str]:
    ids: List[int] = []
    seen = set()
    for value in body_ids:
        if value is None:
            continue
        as_int = int(value)
        if as_int not in seen:
            seen.add(as_int)
            ids.append(as_int)
    newest: Optional[str] = None
    for start in range(0, len(ids), _ID_CHUNK):
        chunk = ids[start:start + _ID_CHUNK]
        marks = ",".join("?" * len(chunk))
        row = conn.execute(
            "SELECT MAX(ts) FROM message_bodies "
            f"WHERE id IN ({marks}) AND ts IS NOT NULL",
            chunk,
        ).fetchone()
        value = row[0] if row else None
        if isinstance(value, str) and (newest is None or value > newest):
            newest = value
    return newest


def classify_activity(newest: Optional[str], counted: bool) -> str:
    """Turn a value plus a did-we-measure flag into one of three tokens.

    Description: the single place the three outcomes are named, so no
      caller re-derives them and gets the boundary wrong. A falsy
      ``counted`` wins over any value, because a timestamp produced by a
      statement that did not run is not a timestamp.
    Inputs: newest (str|None); counted (bool).
    Output: str - one of ACTIVITY_STATUSES.
    Example: classify_activity(None, True) -> 'none'
    """
    if not counted:
        return ACTIVITY_UNKNOWN
    return ACTIVITY_KNOWN if newest else ACTIVITY_NONE


def merge_activity(members: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Bubble several project rows' activity up into one merged node.

      A SINGLE UNMEASURED MEMBER MAKES THE NODE UNMEASURED. If one row's
      timestamp could not be established, the maximum over the rest is a
      lower bound and not the answer, so reporting it as the answer would
      be a verdict nobody measured. The node keeps whatever value the
      measured members produced - it is still the best evidence there is,
      and the rail shows it - but the status says the number is not
      settled, and the ordering treats it accordingly.
    Inputs: members (sequence of dicts carrying ``newest_activity_at``
      and ``activity_counted``).
    Output: {'newest_activity_at': str|None, 'activity_status': str,
             'activity_counted': bool}
    Example: merge_activity([{'newest_activity_at': 'x',
                              'activity_counted': True}])
    """
    newest: Optional[str] = None
    counted = True
    for member in members:
        if not member.get("activity_counted", False):
            counted = False
        value = member.get("newest_activity_at")
        if isinstance(value, str) and value and (newest is None or value > newest):
            newest = value
    return {
        "newest_activity_at": newest,
        "activity_counted": counted,
        "activity_status": classify_activity(newest, counted),
    }
