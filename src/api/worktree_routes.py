from __future__ import annotations

import os
from typing import Any, Dict

from contextlib import closing
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.error_response import api_error
from src.config import settings
from src.core import project_worktree
from src.core.worktrees import cleanup, launch, repo_file
from src.core.worktrees.store import default_store

logger = structlog.get_logger()

router = APIRouter(prefix="/worktrees", tags=["worktrees"])

_CONFLICT_CODES = {"worktree_path_taken", "setup_unapproved"}


def refusal(exc: Exception) -> HTTPException:
    if isinstance(exc, (project_worktree.WorktreeRefused, repo_file.RepoFileRefused)):
        status = 409 if exc.code in _CONFLICT_CODES else 400
        return api_error(status, f"worktree_{exc.code}" if not exc.code.startswith("worktree_") else exc.code, exc,
                         extra={"why": str(exc)}, step="worktree")
    if isinstance(exc, project_worktree.WorktreeTimeout):
        return api_error(504, "worktree_git_timeout", exc, step="worktree")
    return api_error(503, "worktree_git_unavailable", exc, step="worktree")


_REFUSALS = (project_worktree.WorktreeRefused, repo_file.RepoFileRefused, project_worktree.WorktreeTimeout,
             project_worktree.GitUnavailable)


class ApproveSetupRequest(BaseModel):
    """The repository and the exact file hash the owner read and approved."""

    repo: str = Field(..., min_length=1, max_length=4096)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


@router.get("/probe")
async def probe_folder(folder: str = Query(..., min_length=1, max_length=4096),
                       _user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Whether a folder is a repository's top level, its branches, and its repo file. Output: launch.probe's dict."""
    return await launch.probe(folder, default_store())


@router.post("/setup/approve")
async def approve_setup(body: ApproveSetupRequest, _user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Approve the repo file whose CURRENT hash is ``sha256``. A stale hash is refused, never recorded.

    Output: {"approved": true, "sha256"}. Raises: 409 ``worktree_file_changed`` when the file on disk differs.
    """
    repo = os.path.realpath(os.path.expanduser(body.repo))
    try:
        parsed = repo_file.read_repo_file(repo)
    except repo_file.RepoFileRefused as exc:
        raise refusal(exc) from exc
    if parsed is None or parsed.sha256 != body.sha256:
        raise api_error(409, "worktree_file_changed", None, step="worktree_approve")
    default_store().approve(repo, parsed.sha256)
    return {"approved": True, "sha256": parsed.sha256}


async def start_in_worktree(working_dir: str, spec: Any) -> launch.Prepared:
    from src.api.blueprints_launch import StepFailed, ensure_project, worktree_root

    try:
        done = await launch.prepare(working_dir, spec.branch, spec.base_branch, spec.setup, list(spec.copy_files),
                                    root=worktree_root(), store=default_store(),
                                    state_dir=settings.get_state_dir())
    except _REFUSALS as exc:
        raise refusal(exc) from exc
    try:
        ensure_project(done.path, f"{os.path.basename(done.repo)} ({done.branch})")
    except StepFailed as exc:
        raise api_error(400, exc.problem.code, exc, step="worktree_project") from exc
    return done


class CleanupRequest(BaseModel):
    """Plan (``apply`` false) or apply the removal of recorded worktrees."""

    paths: Optional[List[str]] = Field(None, max_length=200, description="Worktree folders; None: every recorded one")
    finished_only: bool = Field(False, description="Plan only merged, clean worktrees (the Sessions page action)")
    apply: bool = False
    fingerprint: Optional[str] = Field(None, max_length=64)
    delete_unmerged: bool = Field(False, description="The second confirm: delete an unmerged branch too")
    remove_dirty: bool = Field(False, description="Remove anyway, after the plan showed the dirty files")


@router.get("")
async def list_worktrees(request: Request, _user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """The worktrees Carnivore made and has not removed, each with the live sessions working in it.

    Output: {"worktrees": [{path, repo, branch, base_branch, sessions: [{id, tmux}]}]} - the session menu offers
      "remove worktree" only on a row listed here.
    """
    manager = request.app.state.session_manager
    held = dict(manager._registry.sessions)
    backends = dict(manager._registry.backends)
    out = []
    for r in default_store().live():
        members = [{"id": sid, "tmux": getattr(backends.get(sid), "tmux_session", None)}
                   for sid, sess in held.items() if _under(r.path, getattr(sess, "working_dir", None))]
        out.append({"path": r.path, "repo": r.repo, "branch": r.branch, "base_branch": r.base_branch, "sessions": members})
    return {"worktrees": out}


def _under(path: str, folder: Optional[str]) -> bool:
    if not folder:
        return False
    real = os.path.realpath(os.path.expanduser(folder))
    return real == path or real.startswith(path.rstrip("/") + "/")


@router.post("/cleanup")
async def cleanup_worktrees(body: CleanupRequest, request: Request,
                            _user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Plan or apply worktree removal. Output: the plan, or {"removed": [...]}.

    Raises: 400 ``worktree_not_offered``, 428 ``worktree_fingerprint_missing``, 412 ``worktree_fingerprint_stale``.
    """
    store = default_store()
    manager = request.app.state.session_manager

    async def stop(path: str) -> None:
        for sid, sess in dict(manager._registry.sessions).items():
            if _under(path, getattr(sess, "working_dir", None)) and manager.is_session_live(sid):
                await manager.destroy_session(session_id=sid)

    async def archive(path: str) -> None:
        from src.api.blueprints_launch import StepFailed, find_project
        from src.core.db import connect, db_path_for
        from src.core.project_archive import archive_project_and_sessions

        try:
            found = find_project(path)
        except StepFailed as exc:
            logger.warning("worktree_cleanup_project_unread", path=path, code=exc.problem.code)
            return
        if found is None or found.get("archived_at") or not isinstance(found.get("id"), int):
            return
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            archive_project_and_sessions(conn, found["id"])

    try:
        if not body.apply:
            return await cleanup.plan(store, body.paths, finished_only=body.finished_only)
        if body.paths is None:
            raise cleanup.CleanupRefused("not_offered", "name the worktrees to remove")
        return await cleanup.apply(store, body.paths, body.fingerprint, stop=stop, archive=archive,
                                   delete_unmerged=body.delete_unmerged, remove_dirty=body.remove_dirty)
    except cleanup.CleanupRefused as exc:
        status = {"fingerprint_missing": 428, "fingerprint_stale": 412}.get(exc.code, 400)
        raise api_error(status, f"worktree_{exc.code}", exc, extra={"why": str(exc)}, step="worktree_cleanup") from exc
    except _REFUSALS as exc:
        raise refusal(exc) from exc
