
from __future__ import annotations

import asyncio
from typing import Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.error_response import soft_failure
from src.api import blueprints_launch as steps
from src.api.auth import require_auth
from src.api.blueprints_reuse import live_sessions
from src.core import blueprints_store as store
from src.core.layouts import store as layouts_store
from src.core import session_change_notice
from src.models.blueprints import LaunchRequest
from src.models.blueprints_launch import LaunchPreviewResponse, LaunchResponse, MemberOutcome

logger = structlog.get_logger()

router = APIRouter()

worktree_root = steps.worktree_root


async def _load(blueprint_uuid: str) -> store.SavedBlueprint:
    from src.api.blueprints_routes import call

    return await call(store.get_blueprint, blueprint_uuid)


def _selected(total: int, members: List[int] | None) -> List[int]:
    if members is None:
        return list(range(total))
    if any(i >= total for i in members):
        raise HTTPException(status_code=400, detail={
            "code": "member_unknown", "detail": f"this blueprint has {total} sessions"})
    return members


@router.post("/{blueprint_uuid}/launch/preview", response_model=LaunchPreviewResponse,
             dependencies=[Depends(require_auth)])
async def preview_launch(blueprint_uuid: str, body: LaunchRequest,
                         request: Request) -> LaunchPreviewResponse:
    """What launching would do, per member: folder, worktree, project, skills.

    Description: WRITES NOTHING. Git is asked (branch names, the base,
      an existing worktree) and a script-bearing skill is staged and
      discarded to produce its consent sheet; no worktree, project,
      skill or session is made. A member whose ``problems`` is empty can
      launch; one with problems will fail at the named step.
    Raises: HTTPException 404, 409, 503.
    """
    saved = await _load(blueprint_uuid)
    root = steps.worktree_root()
    wanted = _selected(len(saved.spec.sessions), body.members)
    needs_catalog = any(saved.spec.sessions[i].skills for i in wanted)
    snapshot = await steps.catalog_snapshot(request) if needs_catalog else None
    members = [await steps.preview_member(request, i, saved.spec.sessions[i], root, snapshot)
               for i in wanted]
    return LaunchPreviewResponse(blueprint_uuid=saved.blueprint_uuid, name=saved.name,
                                 worktree_root=root, members=members)


@router.post("/{blueprint_uuid}/launch", response_model=LaunchResponse,
             dependencies=[Depends(require_auth)])
async def launch(blueprint_uuid: str, body: LaunchRequest, request: Request) -> LaunchResponse:
    """Reuse, wake, then create each member ONE AT A TIME, and save them as a Layout.

    Description: members that already exist go first: a running session is kept
      and an asleep one is woken (the wake route's own function), matched by
      session_uuid, else label + folder; only the rest are created. A member
      that fails stops at its step and the rest still launch; nothing is rolled
      back. Script-bearing skills install only with the consent sent for that
      catalog id (``consents``). Two or more resolved members are saved as the
      blueprint's Layout. When that Layout (same name) already exists the launch
      is REFUSED before anything starts unless ``overwrite_layout`` is true,
      which updates it in place.
    Raises: HTTPException 400 (unknown member index), 404, 409 (``layout_exists``,
      naming the Layout), 503. Every per-member failure is an outcome in the
      200 body, never a status.
    """
    saved = await _load(blueprint_uuid)
    root = steps.worktree_root()
    consents = body.consents or {}
    wanted = _selected(len(saved.spec.sessions), body.members)
    existing_layout = None
    if len(wanted) >= 2:
        try:
            existing_layout = await asyncio.to_thread(steps.find_layout, saved.spec)
        except layouts_store.LayoutError as exc:
            logger.warning("blueprint_layout_lookup_failed", error=str(exc))
        if existing_layout is not None and not body.overwrite_layout:
            raise HTTPException(status_code=409, detail={
                "code": "layout_exists",
                "detail": f"a layout named {existing_layout.name} already exists",
                "layout": {"layout_uuid": existing_layout.layout_uuid, "name": existing_layout.name}})
    live = await live_sessions(request)
    matches = {i: live.match(saved.spec.sessions[i]) for i in wanted}
    outcomes: List[MemberOutcome] = []
    for index in sorted(wanted, key=lambda i: matches[i] is None):
        outcomes.append(await steps.launch_member(
            request, index, saved.spec.sessions[index], root, consents, body.cols, body.rows,
            existing=matches[index]))
    outcomes.sort(key=lambda o: o.index)
    ok = ("launched", "reused", "woken")
    launched: Dict[int, int] = {
        o.index: o.session.session_row_id for o in outcomes
        if o.state in ok and o.session is not None and o.session.session_row_id is not None}
    layout, layout_detail, layout_updated = None, None, False
    if len(launched) >= 2:
        try:
            saved_layout = await asyncio.to_thread(steps.save_layout, saved.spec, launched,
                                                   existing_layout)
        except layouts_store.LayoutError as exc:
            layout_detail = soft_failure("layout_not_saved", exc, status=500, step="save_layout")
        else:
            from src.api.layouts_routes import NOTICE_REASON, to_model

            layout = to_model(saved_layout).model_dump(mode="json")
            layout_updated = existing_layout is not None
            session_change_notice.publish(
                request.app.state, session_change_notice.build_structural_notice(NOTICE_REASON))
    else:
        layout_detail = "a layout needs two or more launched sessions"
    complete = all(o.state in ok for o in outcomes)
    logger.info("blueprint_launched", blueprint_uuid=blueprint_uuid, members=len(outcomes),
                launched=len(launched), complete=complete, layout_updated=layout_updated)
    return LaunchResponse(blueprint_uuid=saved.blueprint_uuid, name=saved.name,
                          complete=complete, members=outcomes, layout=layout,
                          layout_detail=layout_detail, layout_updated=layout_updated)
