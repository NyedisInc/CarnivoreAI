
from __future__ import annotations

import sqlite3
from typing import Any, Dict, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.auth import require_auth
from src.api.swarm_routes import NEEDS_ON, NEEDS_PORT, _manager, _project_missing, _refused
from src.core import db
from src.core.swarm import body, membership, project_agent, views
from src.core.swarm.body import BodyError
from src.models.swarm import SwarmAgentDetail, SwarmJoinRequest, SwarmLeaveRequest, SwarmLeaveResponse, SwarmMembershipSetting

router = APIRouter(prefix="/swarm", tags=["swarm"], dependencies=[Depends(require_auth)])


def _member_refused(exc: membership.MembershipRefused) -> NoReturn:
    raise HTTPException(status_code=404 if exc.code == "not_found" else 409, detail=exc.body()) from exc


@router.post("/members", response_model=SwarmAgentDetail, dependencies=NEEDS_ON)
async def join_swarm(payload: SwarmJoinRequest, request: Request) -> Dict[str, Any]:
    """Make a session a Swarm member under its project agent; it restarts on the same conversation with the Swarm flags.

    Raises: 404 ``not_found``; 409 ``restart_needed`` (no ``confirm_restart``: ``name``, ``busy``, ``sentence``), ``no_project_agent``,
      ``refused``, ``needs_update`` (a paired computer that cannot adopt a session yet), ``swarm_refused`` (the resume failed: the
      member is bound and asleep, a wake retries); 503 (datastore unreadable). Nothing changes on any 4xx but ``swarm_refused``.
    """
    try:
        agent = await membership.join(request.app.state, payload.session_uuid, specialty=payload.specialty,
                                      confirm_restart=payload.confirm_restart, create_project_agent=payload.create_project_agent)
    except membership.MembershipRefused as exc:
        _member_refused(exc)
    except project_agent.TurnOnError as exc:
        raise HTTPException(status_code=409, detail={"code": "refused", "sentence": str(exc)}) from exc
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
    return await views.detail(_manager(request), agent["id"])


@router.delete("/members/{session_uuid}", response_model=SwarmLeaveResponse, dependencies=NEEDS_PORT)
async def leave_swarm(session_uuid: str, request: Request, payload: Optional[SwarmLeaveRequest] = None,
                      confirm_restart: bool = Query(False)) -> Dict[str, Any]:
    """Take a member out of the Swarm: it restarts as a plain session on the same conversation; its agent row is parked.

    ``confirm_restart`` rides in the JSON body or as a query parameter (some clients send no body on DELETE); either true confirms.

    Raises: 404 ``not_found``; 409 ``restart_needed``, ``refused`` (not a member), ``needs_update``, ``swarm_refused`` (it would not
      sleep); 503 (datastore unreadable).
    """
    try:
        return await membership.leave(request.app.state, session_uuid,
                                      confirm_restart=confirm_restart or (payload or SwarmLeaveRequest()).confirm_restart)
    except membership.MembershipRefused as exc:
        _member_refused(exc)
    except (BodyError, db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


def _membership(conn: sqlite3.Connection, project_id: int, value: Optional[bool] = None) -> Dict[str, Any]:
    if value is not None:
        with conn:
            conn.execute("UPDATE projects SET new_sessions_join_swarm = ? WHERE id = ?", (int(value), project_id))
    row = conn.execute("SELECT new_sessions_join_swarm FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise LookupError(project_id)
    return {"new_sessions_join_swarm": bool(row[0])}


@router.get("/projects/{project_id}/membership", response_model=SwarmMembershipSetting)
async def get_project_membership(project_id: int) -> Dict[str, Any]:
    """Whether a new session of the project launches as a Swarm member (off by default). Raises: 404 ``project_not_found``, 503."""
    try:
        return await body.run_db(lambda c: _membership(c, project_id))
    except LookupError:
        raise _project_missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)


@router.put("/projects/{project_id}/membership", response_model=SwarmMembershipSetting)
async def put_project_membership(project_id: int, payload: SwarmMembershipSetting) -> Dict[str, Any]:
    """Turn "new sessions join the swarm" on or off for the project. Raises: 404 ``project_not_found``, 503 (datastore unreadable)."""
    try:
        return await body.run_db(lambda c: _membership(c, project_id, payload.new_sessions_join_swarm))
    except LookupError:
        raise _project_missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
