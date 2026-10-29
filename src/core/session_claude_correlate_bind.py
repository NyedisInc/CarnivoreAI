"""Write a filesystem-correlated ``claude_session_uuid`` onto an anchor row.

THE OTHER HALF OF ``claude_transcript_correlate.py``. That module only
reads the filesystem and never touches the database, so it can stay a
small pure function fixtured entirely in-memory. This module is the one
write path for what it finds, and it owns the three safety properties the
task demands of that write, none of which the reader can enforce on its
own:

  THE UNIQUE INDEX (v12, ``ux_sessions_claude_uuid``). A uuid already on
  another row is not this function's problem to solve - it means either
  the same conversation is already tracked somewhere (nothing to do) or
  the correlation is wrong (also nothing to do, and certainly not an
  overwrite). :func:`bind_correlated_uuid` checks first with the exact
  lookup ``session_lineage.row_for_claude_uuid`` already uses, so the
  common case never reaches SQLite's own constraint at all; the
  ``sqlite3.IntegrityError`` catch below exists only for the race between
  that check and the write, and is reported the same way, never re-raised.

  NEVER RESURRECT, NEVER UN-ARCHIVE. The UPDATE statement here touches
  exactly three columns - ``claude_session_uuid``,
  ``claude_session_uuid_source``, ``updated_at`` - and nothing else on
  the row. It cannot clear ``archived_at`` because it never mentions it.

  ONLY EVER BINDS THE ANCHOR THAT WAS JUST CLAIMED. This is not a general
  lineage writer - it does not fork, and it does not walk a lineage head
  the way ``session_lineage.record_claude_session`` does for the hook
  path. It writes straight to the tmux instance's own anchor row (the one
  ``session_identity.claim_instance`` just claimed) and only when that
  row carries no uuid of its own yet. A row that already carries a
  DIFFERENT uuid is left alone and reported unresolved: that anchor's
  identity was already settled by something else (almost certainly the
  hook, which can only have won a race that started after this adopt),
  and correlation does not get to relitigate it.

FOUR OUTCOMES, NEVER TWO.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    SESSION_CLAUDE_UUID_SOURCE_HOOK,
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
    SESSION_CLAUDE_UUID_SOURCES,
)
from src.core.session_lineage import row_for_claude_uuid
from src.core.session_store import get_instance, sessions_table_ready
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

_NOT_CORRELATED = (
    SESSION_CLAUDE_UUID_SOURCE_HOOK,
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
)

BIND_BOUND = "bound"

BIND_REBOUND = "rebound"

BIND_ALREADY_KNOWN = "already_known"

# COULD NOT EVALUATE
BIND_UNRESOLVED = "unresolved"

BIND_NO_WRITE = (BIND_ALREADY_KNOWN, BIND_UNRESOLVED)


@dataclass(frozen=True)
class BindResult:

    outcome: str
    row_id: Optional[int] = None
    detail: Optional[str] = None

    took_from_row_id: Optional[int] = None

    @property
    def wrote(self) -> bool:
        return self.outcome not in BIND_NO_WRITE


def _row_to_release(
    conn: sqlite3.Connection,
    *,
    known_row_id: int,
    takes_from_row_id: Optional[int],
    socket: str,
    name: str,
    epoch: Optional[int],
) -> Optional[int]:
    """Which row, if any, may release this conversation? None means NONE.

    Description: the whole of the takeover permission, in one place so
      that the caller's measurement and this writer's check cannot drift.
      THREE SEPARATE CONDITIONS, ALL REQUIRED:

        1. The caller asked, by naming a row id. Absent means the historic
           behaviour, where a uuid on another row is ALREADY_KNOWN.
        2. The row it named is the row that ACTUALLY holds the uuid right
           now, re-read inside the caller's transaction. A measurement is
           taken before the transaction opens and the table may have moved
           since; naming a row that no longer holds it is a stale decision
           and is refused, exactly as ``replaces_uuid`` is.
        3. That row is NOT the anchor this call is writing to. A row
           cannot release a conversation to itself, and treating that as a
           takeover would turn the idempotent case into a clear followed
           by a rewrite.
    Inputs: conn (sqlite3.Connection) - inside the caller's transaction.
      known_row_id (int) - the row ``row_for_claude_uuid`` found.
      takes_from_row_id (int | None) - the row the caller measured retired.
      socket (str), name (str), epoch (int | None) - the target instance
      triple, to resolve the anchor for condition 3.
    Output: int | None - the row id to clear, or None to refuse.
    Example: _row_to_release(conn, known_row_id=28, takes_from_row_id=28,
      socket='cloude', name='cloude_Storefront', epoch=1789065709)  # 28
    """
    if takes_from_row_id is None:
        return None
    if known_row_id != int(takes_from_row_id):
        return None
    anchor = get_instance(conn, socket=socket, name=name, epoch=epoch)
    if anchor is None or int(anchor["id"]) == known_row_id:
        return None
    return known_row_id


def bind_correlated_uuid(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    claude_uuid: str,
    source: str = SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    replaces_uuid: Optional[str] = None,
    takes_from_row_id: Optional[int] = None,
    now: Optional[str] = None,
) -> BindResult:
    stamp = now or utc_now()

    if not sessions_table_ready(conn):
        return BindResult(
            outcome=BIND_UNRESOLVED,
            detail="the datastore has no sessions table (pre-v2)",
        )
    if not claude_uuid:
        return BindResult(
            outcome=BIND_UNRESOLVED,
            detail="no claude_session_uuid was resolved to bind",
        )

    known = row_for_claude_uuid(conn, claude_uuid)
    release_from: Optional[int] = None
    if known is not None:
        release_from = _row_to_release(
            conn,
            known_row_id=int(known["id"]),
            takes_from_row_id=takes_from_row_id,
            socket=socket,
            name=name,
            epoch=epoch,
        )
        if release_from is None:
            return BindResult(
                outcome=BIND_ALREADY_KNOWN,
                row_id=int(known["id"]),
                detail=f"session {claude_uuid} is already recorded",
            )

    anchor = get_instance(conn, socket=socket, name=name, epoch=epoch)
    if anchor is None:
        return BindResult(
            outcome=BIND_UNRESOLVED,
            detail=(
                "no sessions row carries this tmux instance triple "
                f"({socket}/{name}/{epoch})"
            ),
        )

    incumbent = anchor.get("claude_session_uuid")
    replacing = bool(incumbent) and bool(replaces_uuid) and incumbent == replaces_uuid
    if incumbent and not replacing:
        return BindResult(
            outcome=BIND_UNRESOLVED,
            row_id=int(anchor["id"]),
            detail=(
                "the anchor row already carries a different "
                "claude_session_uuid"
                if not replaces_uuid
                else (
                    "the anchor row carries a claude_session_uuid the "
                    "caller did not measure, so the rebind decision is stale"
                )
            ),
        )

    honest_registry_rebind = (
        replacing or release_from is not None
    ) and source == SESSION_CLAUDE_UUID_SOURCE_REGISTRY
    if not honest_registry_rebind and (
        source not in SESSION_CLAUDE_UUID_SOURCES or source in _NOT_CORRELATED
    ):
        logger.warning(
            "claude_uuid_correlate_bind_unknown_source",
            requested_source=source,
            note="not a recognised correlated provenance; downgraded to the "
            "timing default rather than written verbatim",
        )
        source = SESSION_CLAUDE_UUID_SOURCE_CORRELATED

    try:
        if release_from is not None:
            conn.execute(
                "UPDATE sessions SET claude_session_uuid = NULL, "
                "claude_session_uuid_source = NULL, updated_at = ? "
                "WHERE id = ? AND claude_session_uuid = ?",
                (stamp, int(release_from), claude_uuid),
            )
        conn.execute(
            "UPDATE sessions SET claude_session_uuid = ?, "
            "claude_session_uuid_source = ?, updated_at = ? WHERE id = ?",
            (
                claude_uuid,
                source,
                stamp,
                int(anchor["id"]),
            ),
        )
    except sqlite3.IntegrityError as exc:
        logger.warning(
            "claude_uuid_correlate_bind_race",
            row_id=int(anchor["id"]),
            claude_session_uuid=claude_uuid,
            error=str(exc),
        )
        return BindResult(
            outcome=BIND_UNRESOLVED,
            row_id=int(anchor["id"]),
            detail=f"unique constraint raced this write: {exc}",
        )

    logger.info(
        "claude_uuid_rebound" if replacing else "claude_uuid_correlated",
        row_id=int(anchor["id"]),
        tmux_name=name,
        claude_session_uuid=claude_uuid,
        replaced_claude_session_uuid=replaces_uuid if replacing else None,
        released_from_row_id=release_from,
        source=source,
    )
    return BindResult(
        outcome=BIND_REBOUND if replacing else BIND_BOUND,
        row_id=int(anchor["id"]),
        took_from_row_id=release_from,
    )
