
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
    SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.session_pane_death import (
    LIFECYCLE_SOURCE_PANE_DEAD,
    pane_death,
)
from src.core.session_respawn import PANE_ALIVE
from src.core.db_reuse.executor import Executor
from src.core.session_store import sessions_table_ready
from src.core.tmux_listing import TmuxListing
from src.core.trail_entry import utc_now
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()


RECONCILE_EVALUATED = "evaluated"

RECONCILE_PROBE_UNAVAILABLE = "probe_unavailable"

RECONCILE_LISTING_INCOMPLETE = "listing_incomplete"

RECONCILE_NO_TABLE = "no_sessions_table"


@dataclass(frozen=True)
class ReconcileOutcome:

    outcome: str
    evaluated: bool
    stopped_uuids: Tuple[str, ...] = field(default_factory=tuple)
    examined: int = 0
    pane_dead_stopped: int = 0
    renamed: int = 0
    revived: int = 0
    reason: Optional[str] = None
    detail: Optional[str] = None

    @property
    def changed(self) -> bool:
        return bool(self.stopped_uuids) or self.renamed > 0 or self.revived > 0


def _not_evaluated(
    outcome: str, reason: Optional[str], detail: Optional[str]
) -> ReconcileOutcome:
    return ReconcileOutcome(
        outcome=outcome,
        evaluated=False,
        stopped_uuids=tuple(),
        examined=0,
        reason=reason,
        detail=detail,
    )


def live_instance_keys(rows: Sequence[Any]) -> Optional[Set[Tuple[str, int]]]:
    keys: Set[Tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            return None
        name = row.get("name")
        epoch = row.get("created_at_epoch")
        if not isinstance(name, str) or not name:
            return None
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            return None
        keys.add((name, int(epoch)))
    return keys


def rename_map(rows: Sequence[Any]) -> Dict[Tuple[int, str], str]:
    seen: Dict[Tuple[int, str], str] = {}
    ambiguous: Set[Tuple[int, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        epoch = row.get("created_at_epoch")
        sid = row.get("session_id")
        if not isinstance(name, str) or not name:
            continue
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            continue
        if not isinstance(sid, str) or not sid:
            continue
        key = (int(epoch), sid)
        if key in seen:
            ambiguous.add(key)
            continue
        seen[key] = name
    for key in ambiguous:
        seen.pop(key, None)
    return seen


def _running_candidates(
    conn: sqlite3.Connection, *, socket: str, host_key: str = LOCAL_HOST_KEY
) -> List[Dict[str, Any]]:
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT id, session_uuid, tmux_name, tmux_created_epoch, "
        "tmux_session_id, archived_at "
        f"FROM sessions WHERE tmux_socket = ?{scope_sql} AND lifecycle = ? "
        "AND tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL",
        (socket, *scope_params, SESSION_LIFECYCLE_RUNNING),
    ).fetchall()
    return [dict(row) for row in rows]


def _reap_absent_instances(
    conn: sqlite3.Connection,
    *,
    listing: TmuxListing,
    socket: str,
    pane_status: Optional[Dict[str, Any]] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> ReconcileOutcome:
    live = live_instance_keys(listing.sessions)
    if live is None:
        logger.warning(
            "session_lifecycle_listing_row_unidentifiable",
            tmux_socket=socket,
            note=(
                "a listing row carried no usable (name, epoch); refusing "
                "to reap, because a stored row matching that instance "
                "would look absent and be stopped while alive"
            ),
        )
        return _not_evaluated(
            RECONCILE_LISTING_INCOMPLETE,
            listing.reason,
            "a listing row carried no usable (name, epoch) identity",
        )

    candidates = _running_candidates(conn, socket=socket, host_key=host_key)
    stamp = now or utc_now()
    stopped: List[str] = []
    renamed = 0
    pane_dead_stopped = 0

    live_names = rename_map(listing.sessions)
    stored_by_key: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for row in candidates:
        sid = row.get("tmux_session_id")
        if isinstance(sid, str) and sid:
            key = (int(row["tmux_created_epoch"]), sid)
            stored_by_key.setdefault(key, []).append(row)

    for key, rows_for_key in stored_by_key.items():
        if len(rows_for_key) != 1:
            logger.warning(
                "session_rename_ambiguous",
                tmux_socket=socket,
                tmux_created_epoch=key[0],
                tmux_session_id=key[1],
                stored_rows=len(rows_for_key),
                note=(
                    "more than one stored row carries this discriminator; "
                    "no rename applied, both rows reconcile normally"
                ),
            )
            continue
        row = rows_for_key[0]
        live_name = live_names.get(key)
        if live_name is None or live_name == str(row["tmux_name"]):
            continue
        if (live_name, key[0]) in {
            (str(other["tmux_name"]), int(other["tmux_created_epoch"]))
            for other in candidates
            if other["id"] != row["id"]
        }:
            continue
        conn.execute(
            "UPDATE sessions SET tmux_name = ?, lifecycle_checked_at = ?, "
            "updated_at = ? WHERE id = ? AND lifecycle = ?",
            (
                live_name,
                stamp,
                stamp,
                int(row["id"]),
                SESSION_LIFECYCLE_RUNNING,
            ),
        )
        logger.info(
            "session_renamed_in_place",
            session_id=int(row["id"]),
            session_uuid=row["session_uuid"],
            tmux_socket=socket,
            tmux_created_epoch=key[0],
            tmux_session_id=key[1],
            old_name=row["tmux_name"],
            new_name=live_name,
            note=(
                "same epoch and same tmux id under a new name: one "
                "session relabelled. session_uuid, origin, pins, unread "
                "and lineage all ride on the row and are untouched"
            ),
        )
        row["tmux_name"] = live_name
        renamed += 1

    for row in candidates:
        key = (str(row["tmux_name"]), int(row["tmux_created_epoch"]))
        if key in live:
            death = pane_death(
                pane_status,
                str(row["tmux_name"]),
                int(row["tmux_created_epoch"]),
                backend_socket=socket,
            )
            if not death.dead:
                continue
            conn.execute(
                "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
                "lifecycle_checked_at = ?, updated_at = ? "
                "WHERE id = ? AND lifecycle = ?",
                (
                    SESSION_LIFECYCLE_STOPPED,
                    LIFECYCLE_SOURCE_PANE_DEAD,
                    stamp,
                    stamp,
                    int(row["id"]),
                    SESSION_LIFECYCLE_RUNNING,
                ),
            )
            stopped.append(str(row["session_uuid"]))
            pane_dead_stopped += 1
            logger.info(
                "session_lifecycle_reaped_pane_dead",
                session_id=int(row["id"]),
                session_uuid=row["session_uuid"],
                tmux_socket=socket,
                tmux_name=row["tmux_name"],
                tmux_created_epoch=int(row["tmux_created_epoch"]),
                archived=row.get("archived_at") is not None,
                lifecycle_source=LIFECYCLE_SOURCE_PANE_DEAD,
                pane_dead=death.pane_dead_raw,
                evidence=death.detail,
                note=(
                    "tmux still lists this session (remain-on-exit) but "
                    "measured its pane dead; the row moves to RECENT. The "
                    "tmux session itself is NOT killed - the husk holds "
                    "the pane's final screen. archived_at not written"
                ),
            )
            continue
        conn.execute(
            "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
            "lifecycle_checked_at = ?, updated_at = ? "
            "WHERE id = ? AND lifecycle = ?",
            (
                SESSION_LIFECYCLE_STOPPED,
                SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
                stamp,
                stamp,
                int(row["id"]),
                SESSION_LIFECYCLE_RUNNING,
            ),
        )
        stopped.append(str(row["session_uuid"]))
        logger.info(
            "session_lifecycle_reaped",
            session_id=int(row["id"]),
            session_uuid=row["session_uuid"],
            tmux_socket=socket,
            tmux_name=row["tmux_name"],
            tmux_created_epoch=int(row["tmux_created_epoch"]),
            archived=row.get("archived_at") is not None,
            lifecycle_source=SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
            note=(
                "instance absent from a complete tmux listing; "
                "archived_at deliberately not written"
            ),
        )

    revived = 0
    for row in _revivable_pane_dead_rows(
        conn, live=live, socket=socket, pane_status=pane_status,
        host_key=host_key,
    ):
        conn.execute(
            "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
            "lifecycle_checked_at = ?, updated_at = ? "
            "WHERE id = ? AND lifecycle = ? AND lifecycle_source = ?",
            (
                SESSION_LIFECYCLE_RUNNING,
                SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
                stamp, stamp,
                int(row["id"]),
                SESSION_LIFECYCLE_STOPPED,
                LIFECYCLE_SOURCE_PANE_DEAD,
            ),
        )
        revived += 1
        logger.info(
            "session_lifecycle_revived_pane_alive",
            session_id=int(row["id"]),
            session_uuid=row["session_uuid"],
            tmux_socket=socket,
            tmux_name=row["tmux_name"],
            tmux_created_epoch=int(row["tmux_created_epoch"]),
            lifecycle_source=SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
            note=(
                "same instance, pane measured alive after a pane_dead "
                "stop; the row returns to running"
            ),
        )

    return ReconcileOutcome(
        outcome=RECONCILE_EVALUATED,
        evaluated=True,
        stopped_uuids=tuple(stopped),
        examined=len(candidates),
        pane_dead_stopped=pane_dead_stopped,
        renamed=renamed,
        revived=revived,
        reason=listing.reason,
        detail=_reconcile_detail(renamed, revived),
    )


def _reconcile_detail(renamed: int, revived: int) -> Optional[str]:
    parts = []
    if renamed:
        parts.append(f"renamed {renamed} row(s) in place")
    if revived:
        parts.append(f"revived {revived} pane_dead row(s) whose pane is alive again")
    return "; ".join(parts) or None


def _revivable_pane_dead_rows(
    conn: sqlite3.Connection,
    *,
    live: Set[Tuple[str, int]],
    socket: str,
    pane_status: Optional[Dict[str, Any]],
    host_key: str = LOCAL_HOST_KEY,
) -> List[Dict[str, Any]]:
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT id, session_uuid, tmux_name, tmux_created_epoch "
        f"FROM sessions WHERE tmux_socket = ?{scope_sql} AND lifecycle = ? "
        "AND lifecycle_source = ? AND tmux_name IS NOT NULL "
        "AND tmux_created_epoch IS NOT NULL",
        (socket, *scope_params, SESSION_LIFECYCLE_STOPPED,
         LIFECYCLE_SOURCE_PANE_DEAD),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        name, epoch = str(row["tmux_name"]), int(row["tmux_created_epoch"])
        if (name, epoch) not in live:
            continue
        verdict = pane_death(pane_status, name, epoch, backend_socket=socket)
        if verdict.outcome == PANE_ALIVE:
            out.append(dict(row))
    return out



def reconcile_from_listing(
    conn: Executor,
    *,
    listing: TmuxListing,
    socket: str,
    pane_status: Optional[Dict[str, Any]] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> ReconcileOutcome:
    if not listing.ok:
        return _not_evaluated(
            RECONCILE_PROBE_UNAVAILABLE, listing.reason, listing.detail
        )
    if not listing.complete:
        return _not_evaluated(
            RECONCILE_LISTING_INCOMPLETE,
            listing.reason,
            f"{listing.refused_rows} tmux row(s) were refused by the parser",
        )
    if not sessions_table_ready(conn):
        return _not_evaluated(RECONCILE_NO_TABLE, listing.reason, None)
    return _reap_absent_instances(
        conn,
        listing=listing,
        socket=socket,
        pane_status=pane_status,
        now=now,
        host_key=host_key,
    )
