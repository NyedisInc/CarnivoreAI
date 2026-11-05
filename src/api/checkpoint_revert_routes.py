
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.api.auth import require_auth, security
from src.api.checkpoint_codex_note import tell_codex
from src.api.checkpoint_routes import _one
from src.api.error_response import api_error
from src.api.project_move_routes import read_live_panes
from src.core.api_keys.store import is_api_key
from src.core.bookmarks import rows
from src.core.checkpoints import revert as revert_mod
from src.core.checkpoints.store import get_store, state_root
from src.core.project_move.paths import is_within
from src.core.project_move.plan import PaneListing

router = APIRouter(tags=["turn-checkpoints"])

BUSY_STATES = frozenset({"working", "working_subagent", "question"})


async def require_owner(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    await require_auth(credentials, request)
    if (credentials is not None and is_api_key(credentials.credentials)) or request.scope.get("via_peer_link"):
        raise api_error(403, "revert_owner_only")


class RevertKept(BaseModel):
    """A path the snapshots differ on that the revert leaves alone."""

    path: str
    reason: str = Field(description="left_out (too big or secret-looking), ignored, in_the_way, submodule, unsafe_path")


class RevertPreview(BaseModel):
    """What a revert to one snapshot would do now, and whether it may."""

    id: int
    work_tree: str
    change: List[str] = Field(description="files that get the snapshot's content back")
    create: List[str] = Field(description="files the snapshot had that are gone now")
    delete: List[str] = Field(description="files made since the snapshot")
    kept: List[RevertKept]
    fingerprint: str = Field(description="quote it in the revert; any drift in the files refuses")
    blocked_by: List[str] = Field(description="why the revert is refused now (empty: it may run)")


class RevertRequest(BaseModel):
    """The owner's confirmation."""

    confirm: bool = Field(description="must be true")
    fingerprint: str = Field(min_length=1, description="the preview's fingerprint")


class RevertDone(BaseModel):
    """What the revert did."""

    id: int
    safety_id: int = Field(description="the snapshot taken first; reverting to it undoes this revert")
    changed: List[str]
    created: List[str]
    deleted: List[str]
    kept: List[RevertKept]
    note_sent: bool = Field(False, description="a Codex session was told in its prompt that its files went back to turn N")
    note_error: Optional[str] = Field(None, description="why a Codex session's note could not go in (the revert is done)")


def isolation_reasons(panes: PaneListing, own_tmux: Optional[str], work_tree: str, own_status: Optional[str]) -> List[str]:
    out: List[str] = []
    if own_status in BUSY_STATES:
        out.append(f"this session is {own_status.replace('_', ' ')}")
    if not panes.ok:
        out.append(f"the live session list did not answer ({panes.reason}), so another session cannot be ruled out")
        return out
    spellings = {work_tree, os.path.realpath(work_tree)}
    for name, _, cwd in panes.panes:
        if not name or name == own_tmux or not cwd:
            continue
        here = {cwd, os.path.realpath(cwd)}
        if any(is_within(a, b) or is_within(b, a) for a in here for b in spellings):
            out.append(f"session {name} is live in {cwd}")
    return out


async def _blocked_by(request: Request, row: rows.SessionRow, work_tree: str, *, include_own: bool = True) -> List[str]:
    manager = request.app.state.session_manager
    status: Optional[str] = None
    if row.tmux_name and include_own:
        for sid in manager._registry.registered_ids_for_tmux_name(row.tmux_name):
            info = await manager.get_session_info(sid)
            if info is not None:
                status = info.activity_status
                break
    panes = await run_in_threadpool(read_live_panes)
    return isolation_reasons(panes, row.tmux_name, work_tree, status)


def _refused(exc: revert_mod.RevertRefused) -> Any:
    extra = {"safety_id": exc.safety_id} if exc.safety_id is not None else None
    return api_error(exc.status, exc.code, exc, extra=extra, why=exc.message)


def _kept(items: List[Dict[str, str]]) -> List[RevertKept]:
    return [RevertKept(**k) for k in items]


@router.get("/sessions/{session_uuid}/checkpoints/{checkpoint_id}/revert/preview", response_model=RevertPreview,
            dependencies=[Depends(require_owner)])
async def revert_preview(request: Request, session_uuid: str, checkpoint_id: int) -> RevertPreview:
    """What reverting the files to this snapshot would change, create and delete now, and whether it may run.

    Changes no file. 404 for an unknown snapshot; 409 or 503 when the snapshot or the files cannot be read.
    """
    cp = await run_in_threadpool(_one, session_uuid, checkpoint_id)
    row = await run_in_threadpool(rows.read_row, cp.session_uuid)
    try:
        plan = await run_in_threadpool(revert_mod.preview, get_store(), cp, state_root())
    except revert_mod.RevertRefused as exc:
        raise _refused(exc) from exc
    blocked = await _blocked_by(request, row, cp.work_tree)
    return RevertPreview(id=cp.id, work_tree=cp.work_tree, change=plan.change, create=plan.create, delete=plan.delete,
                         kept=_kept(plan.kept), fingerprint=plan.fingerprint, blocked_by=blocked)


@router.post("/sessions/{session_uuid}/checkpoints/{checkpoint_id}/revert", response_model=RevertDone,
             dependencies=[Depends(require_owner)])
async def revert_files(request: Request, session_uuid: str, checkpoint_id: int, body: RevertRequest) -> RevertDone:
    """Put the files back to this snapshot, after a safety snapshot of how they are now (kept 7 days).

    The real index, branch and HEAD are never touched; left-out and ignored files never change. 400 without
    ``confirm``; 409 ``revert_blocked`` while another live session shares the folder tree (``blocking`` names them),
    409 ``changed_since_preview`` when the files moved since the preview, 409 or 503 when a snapshot cannot be read or
    taken (nothing changed), 500 ``revert_failed`` part way (``safety_id`` undoes it).
    """
    if not body.confirm:
        raise api_error(400, "revert_confirm_required")
    cp = await run_in_threadpool(_one, session_uuid, checkpoint_id)
    row = await run_in_threadpool(rows.read_row, cp.session_uuid)
    blocked = await _blocked_by(request, row, cp.work_tree)
    if blocked:
        raise api_error(409, "revert_blocked", extra={"blocking": blocked})
    try:
        done = await run_in_threadpool(revert_mod.revert, get_store(), cp, body.fingerprint, state_root())
    except revert_mod.RevertRefused as exc:
        raise _refused(exc) from exc
    sent, why = await tell_codex(request.app.state.session_manager, request.app, row, cp)
    return RevertDone(id=cp.id, safety_id=done.safety.id, changed=done.plan.change, created=done.plan.create,
                      deleted=done.plan.delete, kept=_kept(done.kept), note_sent=sent, note_error=why)
