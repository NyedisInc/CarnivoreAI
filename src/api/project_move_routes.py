
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool

from src.api import projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core import session_change_notice
from src.core.session_roles import check as session_roles_check
from src.core.project_move.apply import MoveBusy, MoveFailed, MoveRefused, apply_plan, one_move_at_a_time
from src.core.project_move.fingerprint import FingerprintError, require_quoted
from src.core.project_move.plan import MovePlan, PaneListing, build_plan
from src.models import ProjectMoveRequest, ProjectMoveResponse
from src.api.error_response import api_error, soft_failure

logger = structlog.get_logger()
router = APIRouter()

NOTICE_REASON = "project_moved"


def read_live_panes() -> PaneListing:
    from src.core.session_backend import build_backend
    from src.core.tmux_listing import coerce_listing

    try:
        probe = build_backend(settings, session_id="__project_move_probe__", working_dir=Path.home(), on_output=None)
        if not hasattr(probe, "list_pane_status_all"):
            return PaneListing(ok=False, reason="this backend cannot list panes")
        listing = coerce_listing(probe.list_pane_status_all(fresh=True))
    except (OSError, ValueError, RuntimeError) as exc:
        return PaneListing(ok=False, reason=soft_failure("pane_listing_failed", exc, step="project_move_panes"))
    if not listing.ok:
        return PaneListing(ok=False, reason=str(listing.reason or "no answer"))
    rows = tuple((r.get("name"), r.get("created_at_epoch"), r.get("pane_current_path")) for r in listing.sessions or ())
    return PaneListing(ok=True, panes=rows)


def _response(plan: MovePlan, done: Any = None) -> ProjectMoveResponse:
    return ProjectMoveResponse(
        project_id=plan.project["id"], project_name=plan.project["name"], old_root=plan.old_root,
        new_root=plan.new_root, new_root_typed=plan.new_root_typed, move_folder=plan.move_folder,
        create_parents=plan.create_parents, folders_to_create=plan.folders_to_create,
        applied=done is not None, ok=plan.ok,
        checks=plan.checks, warnings=plan.warnings, child_projects=plan.children, sessions=plan.sessions,
        conversation_index_rows=plan.conversation_rows, skill_installs=plan.skill_installs,
        transcript_moves=plan.transcript_moves,
        informational=plan.informational, fingerprint=plan.fingerprint, done=done,
    )


def _plan_and_maybe_apply(project_name: str, body: ProjectMoveRequest) -> ProjectMoveResponse:
    if not body.apply:
        return _plan_then_apply(project_name, body)
    try:
        with one_move_at_a_time():
            return _plan_then_apply(project_name, body)
    except MoveBusy as exc:
        raise api_error(409, "move_busy", exc) from exc


def _plan_then_apply(project_name: str, body: ProjectMoveRequest) -> ProjectMoveResponse:
    panes = read_live_panes()
    with closing(projects_service.open_db_or_503(settings)) as conn:
        project = projects_service.resolve_target(conn, project_name)
        plan = build_plan(conn, project, body.new_root, body.move_folder, panes=panes, settings=settings,
                          create_parents=body.create_parents)
        if not body.apply:
            return _response(plan)
        try:
            require_quoted(plan, body.plan_fingerprint)
        except FingerprintError as exc:
            code = "plan_fingerprint_required" if exc.status == 428 else "plan_changed"
            raise api_error(exc.status, code, exc, extra={"plan": _response(plan).model_dump()}) from exc
        try:
            done = apply_plan(conn, plan, state_dir=Path(settings.get_state_dir()))
        except MoveRefused as exc:
            raise api_error(409, "move_refused", exc, extra={"plan": _response(plan).model_dump()}) from exc
        except MoveFailed as exc:
            raise api_error(500, "move_failed", exc, extra={"step": exc.step, "undone": exc.undone},
                            undo_errors=exc.undo_errors) from exc
    return _response(plan, done)


@router.post("/projects/{project_name}/move", response_model=ProjectMoveResponse, dependencies=[Depends(require_auth)])
async def move_project(project_name: str, body: ProjectMoveRequest, request: Request) -> ProjectMoveResponse:
    """Plan or run a move of a project's folder (and its child projects and sessions).

    Description: re-points ``projects.root`` and ``raw_path`` in place (same id)
      for the project and every child project under it, prefix-replaces
      ``sessions.working_dir`` and ``conversation_index.working_dir``, renames
      the Claude transcript folders, and updates the reboot journal. With
      ``move_folder`` it renames the folder here first (creating the missing
      parents the plan lists when ``create_parents``); without it the folder
      must already be at ``new_root``. Refused while any session under the old
      folder is live.
    Inputs: project_name (str, URL) - display name; body (ProjectMoveRequest);
      request - for the event hub.
    Output: ProjectMoveResponse - the plan; ``done`` set after an apply.
    Raises: HTTPException 404 unknown project, 428 an apply quoting no
      ``plan_fingerprint``, 412 one quoting a plan that has since changed,
      409 ambiguous name or a refused apply (each detail carries the plan) or
      another move still running, 500 a step failed (earlier steps undone),
      503 database unreachable or read-only.
    """
    if body.apply:
        projects_service.guard_writable(settings)
    response = await run_in_threadpool(_plan_and_maybe_apply, project_name, body)
    if response.applied:
        app = getattr(request, "app", None)
        if app is not None:
            session_change_notice.publish(app.state, session_change_notice.build_structural_notice(NOTICE_REASON))
            await session_roles_check.after_change(app.state)
    return response
