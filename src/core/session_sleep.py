"""Putting a session to SLEEP: stop its agent and tmux, keep its row, asleep.

ASLEEP IS A LIFECYCLE SOURCE, NOT A NEW COLUMN. An asleep row is
``lifecycle='stopped'`` with ``lifecycle_source='slept_by_user'`` (or
``'slept_by_timer'`` when the auto-sleep pass did it). A companion shell
(issue #1551) is never selected by auto-sleep (``auto_sleep.sleeper.AGENT_FAMILIES``) and a
sleeping agent CLOSES its shell through this module's :func:`close_for_sleep`,
writing the shell row ``lifecycle_source='closed_with_agent'`` (a source word
that is not a sleep source: the shell is not asleep, it is gone until the next
open re-records it on the same row). That is a
durable fact on the row (so a boot, a ghost reap or the lifecycle reaper
cannot lose it: none of them deletes a row, and the reaper writes only over
``running``), and it needs no schema bump, so an older build can still open
the database. It also cannot go stale: every path that brings a row back
(wake, a Recent restart, the reopen offer) goes through
``session_restart.rebind_instance``, which rewrites ``lifecycle`` and
``lifecycle_source``, and a later kill or loss writes its own source over it.

HOW IT DIFFERS FROM KILL, and nothing else does. Kill (``DELETE /sessions``)
writes ``closed_by_user``, which files the row under Recent; it also removes
the session's uploads bucket and drops its pinned theme. Sleep keeps the row
in the running lists, keeps the uploads and the pin (the session is coming
back to them), and refuses a session whose conversation id is not known,
because a sleep that cannot be woken into the same conversation is a kill.

NO SECOND TEARDOWN. A registered session is stopped by its own backend's
``stop()`` (``kill-session -t =<name>`` on its own socket) and forgotten by
``session_ghost_reap.drop_registration``, the registration teardown the ghost
reap and the adopt path already use. A session on the socket with no
registration is killed by exact name on the row's own socket.

THE NAME STAYS RESERVED WHILE ASLEEP (:func:`reserved_names`), or a new
session in the same project could take it and the wake, gated on that name
being measured absent, could never run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

import structlog

from src.core.sessions import offer_reservation
from src.core.db_models import SESSION_LIFECYCLE_RUNNING, SESSION_LIFECYCLE_STOPPED
from src.core.session_pane_death import LIFECYCLE_SOURCE_PANE_DEAD

logger = structlog.get_logger()

LIFECYCLE_SOURCE_SLEPT = "slept_by_user"

LIFECYCLE_SOURCE_SLEPT_BY_TIMER = "slept_by_timer"

SLEEP_SOURCES = frozenset({LIFECYCLE_SOURCE_SLEPT, LIFECYCLE_SOURCE_SLEPT_BY_TIMER})

REFUSED_ARCHIVED = "archived"
REFUSED_NO_TMUX = "no_tmux_identity"
REFUSED_NOT_RUNNING = "not_running"
REFUSED_NO_CONVERSATION = "no_conversation"
REFUSED_PRESENCE_UNKNOWN = "presence_unknown"
REFUSED_ROW_MOVED = "row_moved"
REFUSED_REMOTE_HOST = "remote_host"


@dataclass(frozen=True)
class SleepRefusal:

    code: str
    detail: str


def is_dead_pane_stop(row: Optional[Mapping[str, Any]]) -> bool:
    if not row or row.get("lifecycle") != SESSION_LIFECYCLE_STOPPED:
        return False
    if row.get("lifecycle_source") != LIFECYCLE_SOURCE_PANE_DEAD:
        return False
    uuid = str(row.get("claude_session_uuid") or "").strip()
    return bool(uuid) and not _transcript_absent(row, uuid)


def _transcript_absent(row: Mapping[str, Any], uuid: str) -> bool:
    """Is this row's conversation transcript MEASURED absent from disk (P23)?

    Description: a conversation id with no transcript behind it cannot be resumed, so a dead-pane row holding
      one is closed, not asleep (row 77 "Home"). Asked of the row's own harness: codex rollout store for a
      codex row, every claude transcript root (``locate_transcript``) otherwise. UNCHECKED (a store that could
      not be read) is NOT absence, so the row keeps reading asleep. Results are cached by the presence probe.
    Inputs: row (Mapping) - a ``sessions`` row; uuid (str) - its conversation id.
    Output: bool - True only on a definite ABSENT.
    Example: _transcript_absent({'agent_family': 'codex'}, '019a...')  # True when no rollout exists
    """
    from src.core.attention.evidence import FAMILY_CODEX
    from src.core.session_transcript_presence import CONVERSATION_ABSENT, codex_rollout_presence

    if row.get("agent_family") == FAMILY_CODEX:
        return codex_rollout_presence(uuid).missing
    from src.core.session_token_usage.claude_reader import locate_transcript

    return locate_transcript(uuid, working_dir=row.get("working_dir")).outcome == CONVERSATION_ABSENT


def is_asleep(row: Optional[Mapping[str, Any]]) -> bool:
    if not row or row.get("archived_at"):
        return False
    if row.get("lifecycle") != SESSION_LIFECYCLE_STOPPED:
        return False
    return row.get("lifecycle_source") in SLEEP_SOURCES or is_dead_pane_stop(row)


def is_closed(row: Optional[Mapping[str, Any]]) -> bool:
    """Is this stored row CLOSED: stopped on purpose or gone, not asleep, not deleted? PURE.

    Description: a closed session (#1845) is a real process that ended (the user closed it, or tmux lost it) and that
      the user has not archived. It is not asleep (nothing promises a wake), not archived (the user has not removed
      it from the lists) and not a lineage row (no tmux creation epoch: it describes a conversation, not a process).
      The drawer lists it with its own "closed" look until the user reopens or archives it.
    Inputs: row (Mapping | None) - a ``sessions`` row.
    Output: bool.
    Example: is_closed({'lifecycle': 'stopped', 'lifecycle_source': 'closed_by_user',
      'tmux_created_epoch': 1, 'archived_at': None})  # True
    """
    if not row or row.get("archived_at"):
        return False
    if row.get("lifecycle") != SESSION_LIFECYCLE_STOPPED or row.get("tmux_created_epoch") is None:
        return False
    return not is_asleep(row)


def sleep_refusal(row: Mapping[str, Any], *, fresh_ok: bool = False) -> Optional[SleepRefusal]:
    """Whether this row may be put to sleep, and why not. PURE.

    Description: the gates, in order. THE CONVERSATION GATE USES THE SAME
      CLASSIFIER THE WAKE WILL (``session_resume_target.resume_target_from_row``
      is what ``recreate_routes._gather`` builds its ``--resume`` from), so a
      row this lets through is one the wake can resume by construction.
    Inputs: row (Mapping) - the ``sessions`` row, read by ``session_uuid``. fresh_ok
      (bool) - a Swarm sleep: the no-conversation gate is skipped, because a body
      that never finished a turn has no conversation id and its next wake is fresh.
    Output: SleepRefusal | None - None means every gate passed.
    Example: sleep_refusal({'lifecycle': 'running', 'tmux_name': 'a',
      'tmux_created_epoch': 1, 'claude_session_uuid': None}).code
      # 'no_conversation'
    """
    from src.core.session_recreate import has_tmux_identity
    from src.core.session_resume_target import (
        CONVERSATION_RESUMED,
        resume_target_from_row,
    )

    if row.get("archived_at"):
        return SleepRefusal(
            REFUSED_ARCHIVED, "cannot sleep: this session was deleted"
        )
    if (row.get("host_key") or "local") != "local":
        return SleepRefusal(
            REFUSED_REMOTE_HOST, "cannot sleep: this session runs on another machine"
        )
    if (not has_tmux_identity(row) or not row.get("tmux_name")
            or row.get("tmux_created_epoch") is None):
        return SleepRefusal(
            REFUSED_NO_TMUX,
            "cannot sleep: this session has never had a tmux session to close",
        )
    if row.get("lifecycle") != SESSION_LIFECYCLE_RUNNING:
        return SleepRefusal(
            REFUSED_NOT_RUNNING,
            "cannot sleep: this session is not running, so there is nothing "
            "to stop",
        )
    target = resume_target_from_row(row, row_read_ok=True)
    if target.outcome != CONVERSATION_RESUMED and not fresh_ok:
        return SleepRefusal(
            REFUSED_NO_CONVERSATION,
            "cannot sleep: no conversation id is recorded for this session "
            "yet, so waking it could not resume the same conversation. "
            "nothing was stopped",
        )
    return None


def mark_asleep(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    tmux_name: str,
    tmux_created_epoch: int,
    now: Optional[str] = None,
    source: str = LIFECYCLE_SOURCE_SLEPT,
) -> int:
    from src.core.trail_entry import utc_now

    if source not in SLEEP_SOURCES:
        raise ValueError(f"{source!r} is not a sleep source")
    stamp = now or utc_now()
    cursor = conn.execute(
        "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
        "lifecycle_checked_at = ?, updated_at = ?, "
        "activity_state = NULL, activity_state_at = NULL "
        "WHERE id = ? AND tmux_name = ? AND tmux_created_epoch = ? "
        "AND archived_at IS NULL AND lifecycle IN (?, ?)",
        (
            SESSION_LIFECYCLE_STOPPED,
            source,
            stamp,
            stamp,
            int(row_id),
            tmux_name,
            int(tmux_created_epoch),
            SESSION_LIFECYCLE_RUNNING,
            SESSION_LIFECYCLE_STOPPED,
        ),
    )
    moved = int(cursor.rowcount or 0)
    logger.info(
        "session_sleep_recorded",
        session_id=int(row_id),
        tmux_name=tmux_name,
        tmux_created_epoch=int(tmux_created_epoch),
        lifecycle_source=source,
        rows_moved=moved,
    )
    return moved


def asleep_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    from src.core import session_store

    rows = session_store.list_sessions(
        conn,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
        include_archived=False,
        include_automated=False,
    )
    return [row for row in rows if is_asleep(row)]


def closed_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Every CLOSED, undeleted, user-facing row with a known conversation id, newest first (#1980).

    Description: a closed row (:func:`is_closed`, e.g. ``lifecycle_source='tmux_missing'`` after a reboot) that
      can be reopened through the recreate path, which resumes by the row's ``claude_session_uuid``; a closed row
      without one has nothing to resume and is left out. Same user-facing filter as :func:`asleep_rows`.
    Inputs: conn (sqlite3.Connection). Output: list[dict] - ``sessions`` rows.
    Example: closed_rows(conn)  # [{'session_uuid': 'u1', 'lifecycle_source': 'tmux_missing', ...}]
    """
    from src.core import session_store

    rows = session_store.list_sessions(
        conn,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
        include_archived=False,
        include_automated=False,
    )
    return [row for row in rows if is_closed(row) and str(row.get("claude_session_uuid") or "").strip()]


def companion_names(conn: sqlite3.Connection) -> Set[str]:
    from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
    from src.core.db import column_exists

    if not column_exists(conn, "sessions", COMPANION_OF_COLUMN):
        return set()
    return {str(r[0]) for r in conn.execute(
        f"SELECT tmux_name FROM sessions WHERE {COMPANION_OF_COLUMN} IS NOT NULL AND tmux_name IS NOT NULL")}


def reserved_names(owned: Iterable[str], *, db_path: Optional[Path] = None) -> Set[str]:
    from contextlib import closing

    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    names = set(owned)
    if db_path is None:
        from src.config import settings

        db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        return names | offer_reservation.offered_names(db_path.parent)
    try:
        with closing(connect(db_path, create=False)) as conn:
            names |= {str(r["tmux_name"]) for r in asleep_rows(conn) if r.get("tmux_name")}
            names |= companion_names(conn)
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        logger.warning(
            "session_sleep_reserved_names_unread",
            error=str(exc),
            note="asleep names are not reserved for this create",
        )
    return names | offer_reservation.offered_names(db_path.parent)


async def close_for_sleep(manager: Any, *, name: str, socket: str) -> Dict[str, Any]:
    from src.core.session_ghost_reap import drop_registration

    held = [
        (sid, backend)
        for sid, backend in list(manager._registry.backends.items())
        if getattr(backend, "tmux_session", None) == name
        and (getattr(backend, "socket_name", None) or socket) == socket
    ]
    for sid, backend in held:
        await backend.stop()
        await drop_registration(
            manager, sid, reason="session_sleep", tmux_name=name, release_token=True
        )
    direct_rc: Optional[int] = None
    if not held:
        direct_rc = await _kill_exact(name, socket)
    if name in manager._owned.names:
        manager._owned.names.discard(name)
        try:
            manager._save_session_metadata()
        except (OSError, ValueError) as exc:
            logger.warning("session_sleep_ledger_save_failed", name=name, error=str(exc))
    logger.info(
        "session_sleep_closed",
        tmux_name=name,
        tmux_socket=socket,
        closed_registrations=len(held),
        direct_kill_rc=direct_rc,
    )
    return {"closed_registrations": len(held), "direct_kill_rc": direct_rc}


async def _kill_exact(name: str, socket: str) -> int:
    from src.core.tmux_backend import TmuxBackend

    probe = TmuxBackend.for_external(
        session_name=name, working_dir=Path.home(), on_output=None, socket_name=socket
    )
    rc, _out, err = await probe._run_tmux("kill-session", "-t", f"={name}", check=False)
    text = err.decode("utf-8", errors="replace").strip()
    if rc != 0 and "can't find session" not in text.lower() and "no server" not in text.lower():
        raise RuntimeError(f"tmux kill-session for {name!r} failed (rc={rc}): {text}")
    return rc
