
from __future__ import annotations

import sqlite3
import uuid as _uuid
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import structlog

from src.core.db_models import (
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_FAMILY_SOURCE_UNKNOWN,
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_ADOPTED,
)
from src.core.session_reconcile import (
    RECORD_MERGED,
    RECORD_REFUSALS,
    RECORD_REFUSED_EPOCH_COLLISION,
    RECORD_REFUSED_INSTANCE_MISMATCH,
    reconcile_existing,
)
from src.core.hosts.ddl import HOST_KEY_COLUMN, LOCAL_HOST_KEY, host_scope
from src.core.session_store import get_instance, sessions_table_ready
from src.core.trail_entry import utc_now

logger = structlog.get_logger()


RECORD_INSERTED = "inserted"

_OPTIONAL_INSERT_COLUMNS: Tuple[str, ...] = (
    "project_id",
    "project_attribution",
    "working_dir",
    "legacy_session_id",
    "agent_type",
    "agent_family",
    "agent_family_source",
    "model",
    "claude_session_uuid",
    "pinned_theme",
    "unread_auto",
    "unread_manual",
    "title",
    "adopted_at",
    "tmux_session_id",
)


@dataclass(frozen=True)
class RecordResult:

    outcome: str
    session_id: Optional[int] = None
    session_uuid: Optional[str] = None
    detail: Optional[str] = None

    @property
    def refused(self) -> bool:
        return self.outcome in RECORD_REFUSALS


def new_session_uuid() -> str:
    return str(_uuid.uuid4())


def record_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    origin: str,
    lifecycle: str = SESSION_LIFECYCLE_RUNNING,
    lifecycle_source: Optional[str] = None,
    session_id: Optional[str] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
    **fields: Any,
) -> RecordResult:
    stamp = now or utc_now()
    unknown = set(fields) - set(_OPTIONAL_INSERT_COLUMNS)
    if unknown:
        raise ValueError(
            f"record_instance got unknown column(s): {sorted(unknown)}"
        )

    if session_id is not None:
        fields.setdefault("tmux_session_id", session_id)

    existing = get_instance(conn, socket=socket, name=name, epoch=epoch, host_key=host_key)
    if existing is not None:
        return reconcile_existing(
            conn,
            existing=existing,
            socket=socket,
            name=name,
            epoch=epoch,
            incoming_origin=origin,
            lifecycle=lifecycle,
            lifecycle_source=lifecycle_source,
            incoming_session_id=session_id,
            stamp=stamp,
        )

    session_uuid = new_session_uuid()
    columns = [
        "session_uuid",
        "tmux_socket",
        "tmux_name",
        "tmux_created_epoch",
        "origin",
        "lifecycle",
        "lifecycle_checked_at",
        "lifecycle_source",
        "created_at",
        "updated_at",
    ]
    values: List[Any] = [
        session_uuid,
        socket,
        name,
        None if epoch is None else int(epoch),
        origin,
        lifecycle,
        stamp,
        lifecycle_source,
        stamp,
        stamp,
    ]
    if lifecycle == SESSION_LIFECYCLE_RUNNING:
        columns.append("last_seen_running_at")
        values.append(stamp)
    if host_key != LOCAL_HOST_KEY:
        columns.append(HOST_KEY_COLUMN)
        values.append(host_key)
    for key in _OPTIONAL_INSERT_COLUMNS:
        if key in fields and fields[key] is not None:
            columns.append(key)
            values.append(fields[key])
    if "project_attribution" not in columns:
        columns.append("project_attribution")
        values.append(SESSION_ATTRIBUTION_UNKNOWN)
    if "agent_family_source" not in columns:
        columns.append("agent_family_source")
        values.append(SESSION_FAMILY_SOURCE_UNKNOWN)

    placeholders = ", ".join("?" for _ in columns)
    cursor = conn.execute(
        f"INSERT INTO sessions ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    return RecordResult(
        outcome=RECORD_INSERTED,
        session_id=int(cursor.lastrowid),
        session_uuid=session_uuid,
    )


ADOPT_CLAIMED = "claimed"

ADOPT_NO_SUCH_INSTANCE = "no_such_instance"

ADOPT_NOT_RUNNING = "not_running"

# COULD NOT EVALUATE
ADOPT_NO_DATASTORE = "no_datastore"

ADOPT_FAILURES: Tuple[str, ...] = (
    ADOPT_NO_SUCH_INSTANCE,
    ADOPT_NOT_RUNNING,
    ADOPT_NO_DATASTORE,
)


@dataclass(frozen=True)
class AdoptResult:
    """What one :func:`claim_instance` call did, and why if it did nothing.

    Description: the reason a bare bool was not enough. Adoption can
      fail three distinguishable ways and the caller must render each
      differently: "that session is no longer there, refresh" for a
      missing row, "that session has stopped" for a corpse, and "we
      could not record it" for an unavailable datastore. Collapsing them
      gives the user one message that is wrong two thirds of the time.
    Inputs (constructor): outcome (str) - one of ``ADOPT_CLAIMED`` or a
      member of ``ADOPT_FAILURES``. session_id (int | None) - the row id
      when one was found, including on the ``not_running`` refusal.
      session_uuid (str | None) - the row's external identity when
      found. stored_lifecycle (str | None) - the lifecycle that caused a
      ``not_running`` refusal. detail (str | None) - human-readable
      reason.
    Output: an AdoptResult instance.
    """

    outcome: str
    session_id: Optional[int] = None
    session_uuid: Optional[str] = None
    stored_lifecycle: Optional[str] = None
    detail: Optional[str] = None

    @property
    def claimed(self) -> bool:
        return self.outcome == ADOPT_CLAIMED

    @property
    def determined(self) -> bool:
        return self.outcome != ADOPT_NO_DATASTORE


def adopt_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: int,
    now: Optional[str] = None,
    project_id: Optional[int] = None,
    project_attribution: Optional[str] = None,
    working_dir: Optional[str] = None,
    agent_family_source: Optional[str] = None,
) -> bool:
    """Claim one tmux instance as ours, permanently.

    Description: design section 4.6's adoption statement - one UPDATE,
      keyed on the instance triple so name reuse cannot redirect it onto
      a different process. The caller owns the transaction.

      ``origin`` moves to ``adopted`` and never moves again: this
      function is the only writer of that value, and it has no path back
      to ``observed``.
    Inputs: conn (sqlite3.Connection) - caller owns the transaction.
      socket (str), name (str), epoch (int) - the instance triple.
      now (str | None) - ISO-8601 stamp, defaults to ``utc_now()``.
      project_id (int | None), project_attribution (str | None),
      working_dir (str | None), agent_family_source (str | None) - each
      applied only when not None, so a caller that could not probe a
      value leaves the stored one alone rather than nulling it.
      LIFECYCLE IS GUARDED. The UPDATE requires the row NOT be
      ``stopped``. Adoption is a claim on a LIVE session, and the triple
      alone does not carry liveness - so a client holding a listing from
      before the session died could POST /sessions/adopt and permanently
      mark a corpse as adopted, getting ``True`` back for a process that
      no longer exists. A refused claim is logged with the stored
      lifecycle named, so the two ways of returning False stay
      distinguishable in the log.
    Output: bool - True when a LIVE row was updated. False when no row
      carries that triple (nothing was created, and that is the honest
      answer: adopting a session we have no record of is a caller bug,
      not a row to invent), and False when the row exists but is
      ``stopped``.
      THIS IS NOW A THIN WRAPPER over :func:`claim_instance`, which
      returns WHICH of the outcomes happened. The bool form is kept
      because every existing caller and test only needs "did it stick",
      and because one function deciding and another reporting is how two
      copies of a rule start. There is exactly one implementation.
    Output: bool - True when a LIVE row was updated. False for all three
      failure modes; call :func:`claim_instance` when the difference
      matters, which it does at any surface a user reads.
    Example: adopt_instance(conn, socket='cloude', name='a', epoch=1000)
    """
    return claim_instance(
        conn,
        socket=socket,
        name=name,
        epoch=epoch,
        now=now,
        project_id=project_id,
        project_attribution=project_attribution,
        working_dir=working_dir,
        agent_family_source=agent_family_source,
    ).claimed


def claim_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: int,
    now: Optional[str] = None,
    project_id: Optional[int] = None,
    project_attribution: Optional[str] = None,
    working_dir: Optional[str] = None,
    agent_family_source: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> AdoptResult:
    """Claim one tmux instance as ours, reporting WHICH outcome happened.

    Description: design section 4.6's adoption statement - one UPDATE,
      keyed on the instance triple so name reuse cannot redirect it onto
      a different process. The caller owns the transaction.

      FOUR NAMED OUTCOMES, THREE CLASSES. ``claimed`` is the success.
      ``no_such_instance`` and ``not_running`` are DEFINITE NEGATIVES the
      user can act on - refresh the list, or the session has stopped -
      and neither is an error to raise. ``no_datastore`` is the
      could-not-evaluate: nothing is known to be wrong with the session,
      we simply have nowhere to record the claim, and reporting it as
      either negative would tell the user his session is gone when it is
      sitting right there.

      ``origin`` moves to ``adopted`` and never moves again: this is the
      only writer of that value, and it has no path back to
      ``observed``. A later ``observed`` sighting through
      :func:`record_instance` MERGES and leaves ``origin`` untouched,
      which is what makes the badge survive a restart.

      LIFECYCLE IS GUARDED. The UPDATE requires the row NOT be
      ``stopped``. Adoption is a claim on a LIVE session, and the triple
      alone does not carry liveness - so a client holding a listing from
      before the session died could otherwise permanently mark a corpse
      as adopted.
    Inputs: conn (sqlite3.Connection) - caller owns the transaction.
      socket (str), name (str), epoch (int) - the instance triple.
      now (str | None) - ISO-8601 stamp, defaults to ``utc_now()``.
      project_id (int | None), project_attribution (str | None),
      working_dir (str | None), agent_family_source (str | None) - each
      applied only when not None, so a caller that could not probe a
      value leaves the stored one alone rather than nulling it.
    Output: AdoptResult.
    Example: claim_instance(conn, socket='cloude', name='a', epoch=1000).outcome
    """
    if not sessions_table_ready(conn):
        logger.warning(
            "session_adopt_no_datastore",
            tmux_socket=socket,
            tmux_name=name,
            note=(
                "no sessions table, so the claim COULD NOT BE EVALUATED. "
                "This is not the same as the session being absent"
            ),
        )
        return AdoptResult(
            outcome=ADOPT_NO_DATASTORE,
            detail="the datastore has no sessions table yet",
        )
    stamp = now or utc_now()
    sets = [
        "origin = ?",
        "adopted_at = COALESCE(adopted_at, ?)",
        "updated_at = ?",
    ]
    values: List[Any] = [SESSION_ORIGIN_ADOPTED, stamp, stamp]
    for column, value in (
        ("project_id", project_id),
        ("project_attribution", project_attribution),
        ("working_dir", working_dir),
        ("agent_family_source", agent_family_source),
    ):
        if value is not None:
            sets.append(f"{column} = ?")
            values.append(value)
    scope_sql, scope_params = host_scope(conn, host_key)
    values.extend([socket, *scope_params, name, int(epoch), SESSION_LIFECYCLE_STOPPED])
    cursor = conn.execute(
        f"UPDATE sessions SET {', '.join(sets)} WHERE tmux_socket = ?{scope_sql} "
        "AND tmux_name = ? AND tmux_created_epoch = ? AND lifecycle != ?",
        values,
    )
    if cursor.rowcount > 0:
        claimed = get_instance(conn, socket=socket, name=name, epoch=epoch, host_key=host_key)
        return AdoptResult(
            outcome=ADOPT_CLAIMED,
            session_id=(claimed or {}).get("id"),
            session_uuid=(claimed or {}).get("session_uuid"),
        )

    existing = get_instance(conn, socket=socket, name=name, epoch=epoch, host_key=host_key)
    if existing is None:
        logger.warning(
            "session_adopt_no_such_instance",
            tmux_socket=socket,
            tmux_name=name,
            tmux_created_epoch=int(epoch),
            note=(
                "no row carries this instance triple, so nothing was "
                "claimed. Adoption UPDATES; it never invents a row, "
                "because a row invented here would carry an origin we "
                "have no evidence for"
            ),
        )
        return AdoptResult(
            outcome=ADOPT_NO_SUCH_INSTANCE,
            detail="no session row carries that tmux instance",
        )

    logger.warning(
        "session_adopt_refused_not_running",
        tmux_socket=socket,
        tmux_name=name,
        tmux_created_epoch=int(epoch),
        stored_session_id=existing.get("id"),
        stored_session_uuid=existing.get("session_uuid"),
        stored_lifecycle=existing.get("lifecycle"),
        note=(
            "adoption claims a LIVE session; a stopped row cannot be "
            "adopted because the process it described is gone, and a "
            "client holding a listing from before it died would "
            "otherwise permanently badge a corpse as the user's"
        ),
    )
    return AdoptResult(
        outcome=ADOPT_NOT_RUNNING,
        session_id=existing.get("id"),
        session_uuid=existing.get("session_uuid"),
        stored_lifecycle=existing.get("lifecycle"),
        detail="that session has stopped",
    )
