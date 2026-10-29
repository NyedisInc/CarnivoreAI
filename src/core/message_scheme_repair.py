
from __future__ import annotations

import sqlite3
from typing import List, Tuple

from src.core.message_model_serialize import (
    OPAQUE_SCHEME,
    UUID_SCHEME,
    session_ref_scheme,
)

TRANSCRIPTS_TABLE: str = "message_transcripts"

OLD_CHECK: str = "CHECK (session_ref_scheme IN ('uuid', 'agent'))"
NEW_CHECK: str = "CHECK (session_ref_scheme IN ('uuid', 'agent', 'opaque'))"


class SchemeRepairError(RuntimeError):
    pass


def stored_table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None or row[0] is None:
        return ""
    return str(row[0])


def check_allows_opaque(conn: sqlite3.Connection) -> bool:
    return NEW_CHECK in stored_table_sql(conn, TRANSCRIPTS_TABLE)


def relax_scheme_check(conn: sqlite3.Connection) -> bool:
    sql = stored_table_sql(conn, TRANSCRIPTS_TABLE)
    if sql == "":
        return False
    if NEW_CHECK in sql:
        return False
    if OLD_CHECK not in sql:
        raise SchemeRepairError(
            f"{TRANSCRIPTS_TABLE} does not carry the expected "
            f"session_ref_scheme CHECK. Found: {sql!r}"
        )
    conn.execute("PRAGMA writable_schema=ON")
    try:
        conn.execute(
            "UPDATE sqlite_master SET sql = ? "
            "WHERE type = 'table' AND name = ?",
            (sql.replace(OLD_CHECK, NEW_CHECK), TRANSCRIPTS_TABLE),
        )
    finally:
        conn.execute("PRAGMA writable_schema=RESET")
    return True


def misclassified_rows(conn: sqlite3.Connection) -> List[Tuple[int, str, str]]:
    if stored_table_sql(conn, TRANSCRIPTS_TABLE) == "":
        return []
    found: List[Tuple[int, str, str]] = []
    for row in conn.execute(
        f"SELECT id, session_ref FROM {TRANSCRIPTS_TABLE} "
        "WHERE session_ref_scheme = ? ORDER BY id",
        (UUID_SCHEME,),
    ).fetchall():
        correct = session_ref_scheme(str(row[1]))
        if correct != UUID_SCHEME:
            found.append((int(row[0]), str(row[1]), correct))
    return found


def backfill_opaque_scheme(conn: sqlite3.Connection) -> int:
    rows = misclassified_rows(conn)
    for transcript_id, _ref, correct in rows:
        conn.execute(
            f"UPDATE {TRANSCRIPTS_TABLE} SET session_ref_scheme = ? "
            "WHERE id = ?",
            (correct, transcript_id),
        )
    return len(rows)


def repair_session_ref_schemes(conn: sqlite3.Connection) -> Tuple[bool, int]:
    relaxed = relax_scheme_check(conn)
    if stored_table_sql(conn, TRANSCRIPTS_TABLE) == "":
        return relaxed, 0
    return relaxed, backfill_opaque_scheme(conn)
