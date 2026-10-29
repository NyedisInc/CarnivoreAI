
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.auth import require_auth
from src.api.remote_route_guard import remote_target
from src.core.session_git.diff import EscapesRepository, read_file_diff
from src.core.session_git.watch import GitStatusWatch
from src.core.session_pane_facts import read_pane_facts
from src.models.session_git import GitFile, SessionGitDiff, SessionGitStatus

logger = structlog.get_logger()
router = APIRouter(tags=["session-git"])


def watch_for(app_state: Any) -> GitStatusWatch:
    watch = getattr(app_state, "git_status_watch", None)
    if watch is None:
        watch = GitStatusWatch()
        app_state.git_status_watch = watch
    return watch


async def _session_directory(manager: Any, info: Any) -> Optional[Path]:
    tmux_name = getattr(info, "tmux_session", None)
    if tmux_name:
        facts = await read_pane_facts(manager.tmux_socket_name(), tmux_name)
        if facts.cwd:
            return Path(facts.cwd)
    stored = getattr(getattr(info, "session", None), "working_dir", None)
    return Path(stored) if stored else None


@router.get("/sessions/{session_id}/git-status", response_model=SessionGitStatus, dependencies=[Depends(require_auth)])
async def get_session_git_status(request: Request, session_id: str) -> SessionGitStatus:
    """The repository changes of one session's folder, and a lease that keeps the push going while this client looks.

    Inputs: request (Request); session_id (str) - a session row id (created or ``adopted:``).
    Output: SessionGitStatus - ``unknown`` when git could not be read or no folder is known (never drawn as clean),
      ``not_a_repo`` outside a repository, ``remote`` for a paired-computer session.
    Raises: HTTPException 404 - no session carries this id.
    Example: GET /api/v1/sessions/ses_1/git-status -> {"state": "ok", "branch": "main", ...}
    """
    manager = request.app.state.session_manager
    if remote_target(manager, session_id) is not None:
        return SessionGitStatus(state="remote")
    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    directory = await _session_directory(manager, info)
    if directory is None:
        return SessionGitStatus(state="unknown")
    status = await watch_for(request.app.state).read(session_id, directory)
    stored = getattr(getattr(info, "session", None), "working_dir", None)
    if status.state != "ok" or not stored:
        return status
    real = await asyncio.to_thread(os.path.realpath, stored)
    return status.model_copy(update={"working_dir_real": real})


def _listed(status: SessionGitStatus, path: str) -> Optional[GitFile]:
    return next((f for f in status.files if f.path == path), None)


@router.get("/sessions/{session_id}/git-diff", response_model=SessionGitDiff, dependencies=[Depends(require_auth)])
async def get_session_git_diff(
    request: Request, session_id: str, path: str = Query(..., min_length=1, max_length=4096),
    staged: bool = False,
) -> SessionGitDiff:
    """One changed file's read-only diff since HEAD (an untracked file shows as all added).

    Inputs: request (Request); session_id (str); path (str) - repo-relative, EXACTLY as the git-status listing
      names it (anything else is refused, so no arbitrary file is ever read); staged (bool) - True for only what is
      staged, False (default) for everything since HEAD.
    Output: SessionGitDiff - text capped at 256 KB with ``truncated``; ``binary``, ``sensitive`` (secret-looking
      name) and ``directory`` name the file without showing it; ``unknown`` when git failed (never an empty diff);
      ``remote`` for a paired-computer session.
    Raises: HTTPException 400 - not a plain relative path; 403 - the path leaves the repository by a symlink;
      404 - no such session, no readable repository, or the path is not in the session's current listing.
    Example: GET /api/v1/sessions/ses_1/git-diff?path=src/a.py -> {"state": "ok", "text": "diff --git ..."}
    """
    parts = path.split("/")
    if "\0" in path or path.startswith("/") or ".." in parts:
        raise HTTPException(status_code=400, detail="path must be relative to the repository, without '..'")
    manager = request.app.state.session_manager
    if remote_target(manager, session_id) is not None:
        return SessionGitDiff(state="remote")
    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    directory = await _session_directory(manager, info)
    if directory is None:
        return SessionGitDiff(state="unknown", path=path)
    watch = watch_for(request.app.state)
    status = await watch.read(session_id, directory)
    entry = _listed(status, path)
    if entry is None and status.state == "ok":
        status, _ = await watch.cache.get(directory, force=True)
        entry = _listed(status, path)
    if status.state == "not_a_repo":
        raise HTTPException(status_code=404, detail="this session's folder is not a git repository")
    if status.state != "ok" or status.repo_root is None:
        return SessionGitDiff(state="unknown", path=path)
    if entry is None:
        raise HTTPException(status_code=404, detail="path is not among this session's changed files")
    try:
        return await asyncio.to_thread(read_file_diff, Path(status.repo_root), entry, staged=staged, unborn=status.unborn)
    except EscapesRepository:
        raise HTTPException(status_code=403, detail="path resolves outside the repository")

