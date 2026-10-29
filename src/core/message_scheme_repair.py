
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
    """The CHECK could not be relaxed and the reason is not a sqlite error.

    Description: raised when the stored schema text is neither the old
      form this step knows how to edit nor the new form it produces, so
      the step cannot act without guessing. Raising propagates out of the
      migration's transaction and rolls the chain back, which is correct:
      a half-relaxed constraint is worse than a refused migration.
    """


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
    """Widen the session_ref_scheme CHECK in place, rewriting no row.

    Description: edits sqlite_master's CREATE TABLE text under
      ``PRAGMA writable_schema`` and forces a reparse with RESET so the
      SAME transaction can go on to write the new value. No DROP, no
      CREATE, no INSERT SELECT, so the FK children described in this
      module's header are never at risk. Does nothing at all when the
      table is absent (a build with the message archive gated off) or
      when the constraint has already been widened.
    Inputs: conn (sqlite3.Connection) - inside the caller's transaction.
    Output: bool - True when this call performed the edit, False when
      there was nothing to do. False is not a failure; it is the
      idempotent path and the archive-disabled path.
    Raises: SchemeRepairError - the table exists but its stored text
      matches neither the old constraint nor the new one, so the step
      cannot edit it without guessing.
    Example: relax_scheme_check(conn) -> True
    """
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
