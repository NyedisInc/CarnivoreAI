
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.error_response import api_error
from src.api.remote_route_guard import refuse_remote
from src.config import settings
from src.core.agy import transcripts
from src.core.agy.identity import info_is_agy
from src.core.agy.path_names import resolve_bare
from src.core.agy.state import state_for_conversation
from src.core.session_pane_facts import read_pane_facts
from src.core.terminal_paths import open_app
from src.core.terminal_paths.resolve import resolve
from src.models.terminal_paths import (OpenPathRequest, OpenPathResponse, ResolvedPath, ResolvePathsRequest,
                                       ResolvePathsResponse)

router = APIRouter(tags=["terminal-paths"], dependencies=[Depends(require_auth)])


async def _cwd(request: Request, session_id: str, action: str) -> Optional[str]:
    manager: Any = request.app.state.session_manager
    refuse_remote(manager, session_id, action)
    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    if info.tmux_session:
        facts = await read_pane_facts(manager.tmux_socket_name(), info.tmux_session)
        if facts.cwd:
            return facts.cwd
    return info.session.working_dir if info.session else None


async def _agy_transcript(request: Request, session_id: str) -> Optional[Path]:
    manager: Any = request.app.state.session_manager
    info = await manager.get_session_info(session_id)
    if info is None or not info.tmux_session or not info_is_agy(info):
        return None
    conversation = manager.claude_uuid_for_tmux_name(info.tmux_session)

    def find() -> Optional[Path]:
        state = state_for_conversation(settings.get_state_dir(), conversation) or {}
        named = state.get("transcript_path")
        if isinstance(named, str) and os.path.isfile(named):
            return Path(named)
        return transcripts.transcript_path(conversation) if conversation else None

    return await run_in_threadpool(find)


@router.post("/sessions/{session_id}/paths/resolve", response_model=ResolvePathsResponse)
async def resolve_paths(request: Request, session_id: str, body: ResolvePathsRequest) -> ResolvePathsResponse:
    """Which of these printed paths exist. Inputs: session_id; body. Output: one answer per text, in order.

    Example: POST /api/v1/sessions/ses_1/paths/resolve {"texts": ["README.md:3"]}
      -> {"paths": [{"text": "README.md:3", "path": "/repo/README.md", "kind": "file", "line": 3}]}
    """
    cwd = await _cwd(request, session_id, "the terminal path check")

    answers = await run_in_threadpool(lambda: {t: resolve(t, cwd) for t in body.texts})
    bare = [t for t, r in answers.items() if r is None and "/" not in t]
    if bare:
        transcript = await _agy_transcript(request, session_id)
        for t in bare:
            answers[t] = await run_in_threadpool(resolve_bare, t, transcript)
    return ResolvePathsResponse(paths=[
        ResolvedPath(text=t, path=answers[t].path, kind=answers[t].kind, line=answers[t].line) if answers[t]
        else ResolvedPath(text=t) for t in body.texts])


@router.post("/sessions/{session_id}/paths/open", response_model=OpenPathResponse)
async def open_path(request: Request, session_id: str, body: OpenPathRequest) -> OpenPathResponse:
    """Show a printed path in Finder or open a file in the default browser.

    Raises: HTTPException 404 (nothing by that name), 400 (a folder in the browser), 502 (``open`` failed).
    Example: POST /api/v1/sessions/ses_1/paths/open {"text": "src/a.py", "app": "finder"}
    """
    cwd = await _cwd(request, session_id, "opening a terminal path")
    found = await run_in_threadpool(resolve, body.text, cwd)
    if found is None and "/" not in body.text:
        found = await run_in_threadpool(resolve_bare, body.text, await _agy_transcript(request, session_id))
    if found is None:
        raise HTTPException(status_code=404, detail="no such file or folder")
    if body.app == "browser" and found.kind != "file":
        raise HTTPException(status_code=400, detail="a folder does not open in the browser")
    try:
        await open_app.open_path(found.path, body.app)
    except open_app.OpenFailed as exc:
        raise api_error(502, "terminal_path_open_failed", exc, app=body.app) from exc
    return OpenPathResponse(path=found.path, app=body.app)
