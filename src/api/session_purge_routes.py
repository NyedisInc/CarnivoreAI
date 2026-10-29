
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.config import settings
from src.core import session_change_notice
from src.core.session_roles import check as session_roles_check
from src.core.session_purge.apply import apply_plan, check_gates, one_purge_at_a_time
from src.core.inventory.model import SessionNotFound
from src.core.session_purge.model import PurgeBusy, PurgePlan, PurgeRefused
from src.core.session_purge.plan import build_plan
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter()

NOTICE_REASON = "session_purged"


class SessionPurgeRequest(BaseModel):
    """``apply`` false plans; true runs, quoting ``plan_fingerprint`` and the owner's typed ``confirm_text``."""

    apply: bool = False
    plan_fingerprint: Optional[str] = Field(default=None, max_length=64)
    confirm_text: Optional[str] = Field(default=None, max_length=1000)


def render(plan: PurgePlan, done: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    deleting = plan.to_delete()
    return {
        "session": plan.session.as_dict(), "ok": plan.ok, "complete": plan.complete,
        "blockers": plan.blockers, "warnings": plan.warnings, "shared_with": plan.shared_with,
        "artifacts": [a.as_dict() for a in plan.artifacts],
        "totals": {"artifacts": len(deleting),
                   "rows": sum(a.count for a in deleting if a.kind == "rows"),
                   "files": sum(a.count for a in deleting if a.kind in ("file", "dir")),
                   "bytes": sum(a.size for a in deleting)},
        "confirm_text": plan.session.display_name, "fingerprint": plan.fingerprint,
        "applied": done is not None, "done": done,
    }


def _panes() -> tuple:
    from src.api.project_move_routes import read_live_panes

    listing = read_live_panes()
    return listing.ok, listing.panes


def plan_and_maybe_apply(session_uuid: str, body: SessionPurgeRequest, beast_armed: bool) -> Dict[str, Any]:
    import sqlite3

    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    state_dir = Path(settings.get_state_dir())
    panes = _panes()
    try:
        conn = connect(db_path_for(state_dir), create=False)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="purge_open") from exc
    with closing(conn):
        def fresh() -> PurgePlan:
            return build_plan(conn, session_uuid, state_dir=state_dir,
                              config_path=Path(settings.auth_config_file).expanduser(), panes=panes,
                              pins_path=Path(settings.get_pinned_themes_path()))
        try:
            plan = fresh()
        except SessionNotFound:
            raise HTTPException(status_code=404, detail={"message": f"no session record {session_uuid}"})
        if not body.apply:
            return render(plan)
        try:
            with one_purge_at_a_time():
                plan = fresh()
                check_gates(plan, beast_armed=beast_armed, quoted=body.plan_fingerprint, typed=body.confirm_text)
                done = apply_plan(conn, plan, state_dir=state_dir)
        except PurgeBusy as exc:
            raise api_error(409, "purge_busy", exc, session_uuid=session_uuid) from exc
        except PurgeRefused as exc:
            raise api_error(exc.status, "purge_refused", exc, extra={"plan": render(plan)}, session_uuid=session_uuid) from exc
        except (sqlite3.Error, OSError) as exc:
            raise api_error(500, "purge_failed", exc, session_uuid=session_uuid) from exc
    return render(plan, done)


@router.post("/sessions/records/{session_uuid}/purge", dependencies=[Depends(require_auth)])
async def purge_session(session_uuid: str, body: SessionPurgeRequest, request: Request) -> Dict[str, Any]:
    """Plan or run the hard delete of one asleep session and everything traced to it.

    Description: see the module docstring. A plan needs no gate; an apply needs Beast Mode armed, the plan's
      fingerprint, no blocker and the exact display name typed. The receipt lands in
      ``<state dir>/purge-receipts/``.
    Inputs: session_uuid (str, URL); body (SessionPurgeRequest); request (for the event hub).
    Output: dict - the plan (``artifacts``, ``totals``, ``blockers``, ``fingerprint``, ``confirm_text``), with
      ``done`` (per-artifact outcomes, the receipt path) after an apply.
    Raises: HTTPException 404 unknown session, 403 Beast Mode not armed, 428 no fingerprint, 412 a stale one,
      409 blocked or another purge running, 422 the typed name does not match, 500 the database step failed
      (nothing deleted), 503 no datastore.
    """
    from src.core.mcp import beast_mode

    armed = beast_mode.beast_enabled() if body.apply else False
    result = await run_in_threadpool(plan_and_maybe_apply, session_uuid, body, armed)
    if result["applied"]:
        app = getattr(request, "app", None)
        if app is not None:
            session_change_notice.publish(app.state, session_change_notice.build_structural_notice(NOTICE_REASON))
            await session_roles_check.after_change(app.state)
    return result
