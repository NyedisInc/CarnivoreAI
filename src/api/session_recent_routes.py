
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from src.api.auth import require_auth
from src.config import settings
from src.core.sessions.closed_time import closed_time, order_recent
from src.models import RecentSessionsResponse

from src.api.session_record_payload import _session_record_payload

from fastapi.concurrency import run_in_threadpool

logger = structlog.get_logger()
router = APIRouter()


@router.get(
    "/sessions/recent",
    response_model=RecentSessionsResponse,
    dependencies=[Depends(require_auth)],
)
async def list_recent_sessions(
    request: Request,
    include_archived: bool = Query(
        False,
        description=(
            "Include DELETED (archived) session records alongside the "
            "live ones. Defaults false, which is the pre-existing "
            "behaviour exactly. Archived rows arrive mixed in, each "
            "carrying its own archived_at, so the client distinguishes "
            "them per row. NOTE the vocabulary difference from projects: "
            "a session's archive is a soft DELETE ('take this off my "
            "screen'), a project's archive is a SHELF ('done with this "
            "for now'). Same column shape, different meaning."
        ),
    ),
    include_automated: bool = Query(
        False,
        description=(
            "Include rows classified kind='automated' - a scheduler run "
            "or a headless `claude -p` probe. DEFAULTS FALSE, and it is "
            "ORTHOGONAL to include_archived: both filters apply, so "
            "include_archived=true still hides automated rows unless "
            "this is set too. Rows with kind NULL or 'unknown' are "
            "returned EITHER WAY. No UI sets this."
        ),
    ),
):
    """RECENT (S9): stored ``stopped`` sessions, datastore-backed.

    Description: the query is exactly ``lifecycle='stopped' AND
      archived_at IS NULL`` (unless ``include_archived`` drops the
      second clause) via ``session_store.list_sessions`` - no
      timer, no retention window, the first launcher surface backed by
      the datastore rather than a live probe.

      THREE-OUTCOME GATE ON PROBE HEALTH. The stored rows are only
      returned when ``session_manager.last_probe_health().ok`` is
      True - i.e. the most recent tmux listing (normally the home
      screen's own ``GET /sessions/attachable`` poll) succeeded. A
      failed or never-run probe returns ``state != 'ok'`` and an EMPTY
      ``sessions`` list instead of the stored rows: RESTART safety
      depends on a 'stopped' row being trustworthy right now, and a
      probe we could not just confirm cannot make that promise. This
      never re-probes tmux itself - it reads whatever health the last
      probe (run by any caller) left behind, so viewing RECENT adds no
      tmux load beyond what the launcher already pays.

      DEFENSE IN DEPTH: even though the SQL already filters to
      ``lifecycle='stopped'``, any row that somehow is not exactly
      'stopped' is dropped again here before it reaches the wire. A
      guarantee is only as good as the layer that enforces it, and this
      route is closer to the wire than the query.
    Inputs: request (Request) - unused beyond auth; carries
      ``request.app.state.session_manager``.
    Output: RecentSessionsResponse.
    Raises: HTTPException 503 - the datastore exists but is unreadable.
    """
    return await recent_response(request.app.state, include_archived=include_archived,
                                 include_automated=include_automated)


async def recent_response(app_state: Any, *, include_archived: bool = False,
                          include_automated: bool = False) -> RecentSessionsResponse:
    from contextlib import closing


    from src.core import session_store
    from src.core.db import DatastoreUnreadableError, connect, db_path_for
    from src.core.session_sleep import is_asleep
    from src.core.db_models import (
        SESSION_LIFECYCLE_RUNNING,
        SESSION_LIFECYCLE_STOPPED,
    )

    health = app_state.services.probe_health.health

    if health.ok is not True:
        state = "never_probed" if health.ok is None else "probe_unavailable"
        notice = (
            "Recent sessions CANNOT BE DETERMINED: no tmux probe has "
            "run yet this session."
            if state == "never_probed"
            else "Recent sessions CANNOT BE DETERMINED: the last tmux "
            f"probe failed (reason: {health.reason or 'unknown'}). "
            "Stored history is not shown as fact until a probe succeeds."
        )
        return RecentSessionsResponse(state=state, sessions=[], notice=notice)

    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        return RecentSessionsResponse(state="ok", sessions=[])

    def _read() -> list:
        with closing(connect(db_path, create=False)) as conn:
            rows = session_store.list_sessions(
                conn,
                lifecycle=SESSION_LIFECYCLE_STOPPED,
                include_archived=include_archived,
                include_automated=include_automated,
            )
            try:
                replaced = {
                    int(r["parent_session_id"])
                    for r in conn.execute(
                        "SELECT parent_session_id FROM sessions"
                        " WHERE lifecycle = ?"
                        " AND parent_session_id IS NOT NULL",
                        (SESSION_LIFECYCLE_RUNNING,),
                    ).fetchall()
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "recent_replaced_scan_unavailable",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    note=(
                        "could not read which rows a running session "
                        "replaced; nothing excluded, so a duplicate may "
                        "show rather than a session going missing"
                    ),
                )
                return rows
            if not replaced:
                return rows
            return [
                row for row in rows
                if row.get("id") not in replaced
            ]

    try:
        rows = await run_in_threadpool(_read)
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    stopped_rows = [
        row for row in rows
        if row.get("lifecycle") == SESSION_LIFECYCLE_STOPPED and not is_asleep(row)
        and row.get("origin") != "peer"
    ]
    payloads = []
    for row in order_recent(stopped_rows):
        closed_at, closed_basis = closed_time(row)
        payloads.append(_session_record_payload(row).model_copy(
            update={"closed_at": closed_at, "closed_basis": closed_basis}))
    return RecentSessionsResponse(state="ok", sessions=payloads)
