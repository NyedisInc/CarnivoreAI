
import sqlite3
from contextlib import closing

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from src.api import asleep_wake_listing
from src.api.auth import require_auth
from src.api.peer_auth import require_peer_sessions
from src.config import settings
from src.core.session_roles import check as session_roles_check
from src.core.swarm import leaders as swarm_leaders
from src.core.pipeline import triggers as save_triggers
from src.models import (
    MuteNotificationsRequest,
    NotificationPolicyResponse,
    SessionRecord,
    SuccessResponse,
)
from typing import Any, Callable, Dict, List, Optional, TypeVar

from src.api.session_record_payload import _session_record_payload, attach_host_labels

from fastapi.concurrency import run_in_threadpool
from src.api.error_response import api_error
from src.core import session_store
from src.core.db import DatastoreUnreadableError, connect, db_path_for

logger = structlog.get_logger()
router = APIRouter()

_T = TypeVar("_T")


async def _run_on_store(work: Callable[[sqlite3.Connection], _T], *, step: str) -> _T:
    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        raise api_error(503, "datastore_unavailable", step=step, reason="no datastore file")

    def _on_thread() -> _T:
        with closing(connect(db_path, create=False)) as conn:
            return work(conn)

    try:
        return await run_in_threadpool(_on_thread)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step=step) from exc


@router.get(
    "/sessions/records",
    response_model=List[SessionRecord],
    dependencies=[Depends(require_auth)],
)
async def list_session_records(
    request: Request,
    include_automated: bool = Query(
        False,
        description=(
            "Include rows classified kind='automated' - a scheduler run "
            "or a headless `claude -p` probe. DEFAULTS FALSE, because "
            "the owner's rule is 'lists should always just be mine. the "
            "rest can be found in the archive explorer.' There is no UI "
            "for this flag; it exists so a caller that wants the "
            "complete set can ask for it. Rows with kind NULL or "
            "'unknown' are returned EITHER WAY - not having looked is "
            "not evidence of automation. Nothing here affects /archive, "
            "which reads the transcript archive and never this table."
        ),
    ),
    archived_only: bool = Query(
        False,
        description=(
            "Return ONLY archived rows (``archived_at`` set), narrowed "
            "before projection. A CLOSED row is not archived (#1845) and "
            "rides the pushed records instead. The agents drawer's \"show archived\" "
            "toggle (Joe (ccsliinc), 2026-10-09) reads this while it is "
            "on and never otherwise, so the pushed listing stays small. "
            "Combines with include_automated as usual."
        ),
    ),
):
    """Every stored session row, newest first, archived rows included.

    Description: archived rows are INCLUDED and the caller filters,
      because design section 4.8 makes it a schema-level guarantee that
      archiving never hides a running session - a route that filtered
      here could quietly break that guarantee for the RUNNING group.
    Inputs: request (Request) - unused beyond auth. include_automated
      (bool), archived_only (bool) - see the query descriptions.
    Output: list[SessionRecord] - empty when the datastore is absent or
      has not reached schema v2. That emptiness is reported honestly by
      GET /sessions/import-status, which is where a caller asks whether
      the absence of rows is an answer or a failure.
    Raises: HTTPException 503 - the datastore exists but is unreadable.
    """
    keep = is_archived_row if archived_only else None
    return await stored_record_rows(request.app.state, include_automated=include_automated, keep=keep)


def is_archived_row(row: dict) -> bool:
    return bool(row.get("archived_at"))


def read_stored_rows(db_path: Any, include_automated: bool) -> List[Dict[str, Any]]:
    from src.core import session_store
    from src.core.db_reuse.change_cache import HOT_READS
    from src.core.db_reuse.core_read import lend_pooled_or_raise

    def load() -> List[Dict[str, Any]]:
        with closing(lend_pooled_or_raise(db_path)) as conn:
            found = session_store.list_sessions(conn, include_automated=include_automated)
            attach_host_labels(conn, found)
        return found

    return [dict(row) for row in HOT_READS.fetch(db_path, ("stored_session_rows", include_automated), load)]


async def stored_record_rows(app_state: Any, *, include_automated: bool = False,
                             keep: Optional[Callable[[dict], bool]] = None,
                             infos: Optional[List[Any]] = None, wake_shared: Optional[Dict[str, Any]] = None) -> List[SessionRecord]:
    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        return []

    store = getattr(getattr(app_state, "session_manager", None), "_unread_store", None)

    def project() -> List[SessionRecord]:
        rows = read_stored_rows(db_path, include_automated)
        if keep is not None:
            rows = [row for row in rows if keep(row)]
        return [_session_record_payload(row, store) for row in rows]

    try:
        records = await run_in_threadpool(project)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="project") from exc
    await asleep_wake_listing.stamp_next_wake(app_state, records, infos, wake_shared)
    return records


@router.delete(
    "/sessions/records/{session_uuid}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def delete_session_record(request: Request, session_uuid: str, confirm_name: Optional[str] = None):
    """DELETE one stored session from every listing. KEEP the row.

    Description: a SOFT delete - it stamps ``sessions.archived_at`` and
      nothing else. The row is retained deliberately, because session
      history and transcripts are built on it; "delete" here means "take
      it off my screen", never "remove it from the database".

      THIS IS NOT THE KILL PATH AND THE TWO MUST NOT BE CONFLATED.
      ``DELETE /sessions`` (and ``DELETE /sessions/external/{name}``)
      stop a running process, and the first of them also rmtrees the
      session's project-folder upload buckets (``.carnivore_uploads`` and the
      legacy ``.cloude_uploads``) - real user content. This
      route does none of that. Deleting a row for a session that is
      still running is allowed and merely unlists it; the lifecycle
      reconciler keeps updating it underneath, unseen.

      ADDRESSED BY ``session_uuid``, NOT BY TMUX NAME, because tmux
      reuses names and two rows can differ only by creation epoch. See
      ``session_store.archive_session``.
    Inputs: request (Request) - unused beyond auth. session_uuid (str,
      path) - the row to delete.
    Output: SuccessResponse - ``message`` says whether this call
      performed the delete or found it already deleted. Those are
      different facts and the route reports which one happened rather
      than flattening both into "ok".
    Raises: HTTPException 404 - no row carries that uuid, so nothing was
      deleted. HTTPException 409 - ``leader_protected``: a Swarm leader's row
      needs its exact display name as ``confirm_name`` (query).
      HTTPException 503 - the datastore is absent or unreadable.
    """
    await swarm_leaders.require_confirm(session_uuid=session_uuid, confirm_name=confirm_name)
    try:
        performed = await _run_on_store(lambda conn: session_store.archive_session(conn, session_uuid), step="_write")
    except session_store.SessionNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"no session record {session_uuid}"
        )

    if performed:
        save_triggers.schedule_for_uuid(session_uuid, save_triggers.EVENT_REMOVE)
        await session_roles_check.after_change(request.app.state)

    return SuccessResponse(
        message=(
            "Session deleted from your lists (the record is kept)"
            if performed
            else "Session was already deleted"
        )
    )


@router.patch(
    "/sessions/records/{session_uuid}/notifications",
    response_model=NotificationPolicyResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def set_session_notification_policy(
    request: Request, session_uuid: str, body: MuteNotificationsRequest
):
    """Mute or unmute one session's notifications. Durably.

    Description: writes ``sessions.notifications_muted`` and steps
      ``sessions.notification_policy_generation``, then updates the
      in-memory policy projection the notification producers read so the
      change takes effect immediately rather than at the next boot.

      IT IS A STATE, NOT A TOGGLE. Sending ``{"muted": true}`` twice
      commits once and reports the same answer both times. A toggle would
      make a retry, a double click, or a second open tab flip the setting
      to whatever the race decided.

      THE GENERATION IS WHY THIS RETURNS MORE THAN "ok". Every queued
      notification carries the generation it was raised under, and the
      dispatcher refuses anything that is not current. So this response's
      ``policy_generation`` is what makes "an old alert cannot escape a
      mute/unmute cycle" checkable from outside the server.

      MUTING ACKNOWLEDGES NOTHING. It records a delivery preference and
      touches no toast, no unread flag and no activity state. In
      particular a pending PERMISSION request stays open and the session
      keeps reporting ``question``: claude is still blocked mid-turn
      waiting on a human, and a mute that quietly marked that answered
      would strand it behind a yes/no nobody was ever told about.

      IT DOES NOT REPLAY A BACKLOG EITHER. Unmuting resumes FUTURE alerts
      only. What was suppressed was never queued for later; what was
      already queued is invalidated by the generation step.

      ADDRESSED BY ``session_uuid``, and optionally checked against an
      expected tmux instance - see ``MuteNotificationsRequest`` for why a
      row action fired from a painted list needs that second key.
    Inputs: request (Request) - unused beyond auth. session_uuid (str,
      path) - the row. body (MuteNotificationsRequest).
    Output: NotificationPolicyResponse - the COMMITTED state and
      generation, read back rather than echoed.
    Raises: HTTPException 404 - no row carries that uuid, or the database
      predates schema v26 so there is nowhere to record this.
      HTTPException 409 - the row is not the tmux instance the caller
      named, so the list it was clicked from was stale.
      HTTPException 503 - the datastore is absent or unreadable.
    """
    def _write(conn: sqlite3.Connection) -> dict:
        return session_store.set_notification_mute(
            conn,
            session_uuid,
            muted=body.muted,
            expected_tmux_name=body.expected_tmux_name,
            expected_tmux_created_epoch=body.expected_tmux_created_epoch,
        )

    try:
        committed = await _run_on_store(_write, step="_write")
    except session_store.SessionInstanceMismatchError:
        raise HTTPException(
            status_code=409,
            detail=(
                "that session record is a different tmux instance now - "
                "refresh and try again"
            ),
        )
    except session_store.SessionNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"no session record {session_uuid}"
        )

    session_manager = request.app.state.session_manager
    store = getattr(session_manager, "_notification_policy_store", None)
    if store is not None:
        try:
            store.apply(
                session_uuid,
                muted=committed["muted"],
                generation=committed["generation"],
            )
            store.bind_instance(
                session_uuid,
                tmux_name=committed.get("tmux_name"),
                tmux_created_epoch=committed.get("tmux_created_epoch"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "notification_policy_projection_update_failed",
                session_uuid=session_uuid,
                error=str(exc),
            )

    logger.info(
        "session_notification_policy_set",
        session_uuid=session_uuid,
        muted=committed["muted"],
        policy_generation=committed["generation"],
        changed=committed["changed"],
    )
    return NotificationPolicyResponse(
        muted=bool(committed["muted"]),
        policy_generation=int(committed["generation"]),
    )


@router.post(
    "/sessions/records/{session_uuid}/unarchive",
    response_model=SuccessResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def unarchive_session_record(request: Request, session_uuid: str):
    """Bring an archived session record back onto the user's screens.

    Description: the reverse of ``DELETE /sessions/records/{uuid}``, and
      it exists for the same reason ``POST /projects/{name}/unarchive``
      does - an archive with no way back is a delete wearing a friendlier
      label. Restarting an archived row already clears ``archived_at`` as
      a side effect (``session_restart.rebind_instance``), which is why
      the launchpad UI has relied on restart rather than a dedicated
      control; this route gives the same restore WITHOUT requiring a live
      tmux to restart into.

      IDEMPOTENT. Unarchiving a row that is not archived is a 200, not a
      404 or a 409 - the caller asked for a state (visible again) and
      that state already holds. The message says which of the two
      happened rather than flattening both into "ok".
    Inputs: request (Request) - unused beyond auth. session_uuid (str,
      path) - the row to restore.
    Output: SuccessResponse - ``message`` says whether this call
      performed the restore or found the row already live.
    Raises: HTTPException 404 - no row carries that uuid, so nothing was
      restored. HTTPException 503 - the datastore is absent or unreadable.
    """
    try:
        performed = await _run_on_store(lambda conn: session_store.unarchive_session(conn, session_uuid), step="_write")
    except session_store.SessionNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"no session record {session_uuid}"
        )

    return SuccessResponse(
        message=(
            "Session restored to your lists"
            if performed
            else "Session was already visible"
        )
    )
