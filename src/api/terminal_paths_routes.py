
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.remote_route_guard import refuse_remote
from src.core.session_pane_facts import read_pane_facts
from src.core.terminal_paths import open_app
from src.core.terminal_paths.resolve import resolve
from src.models.terminal_paths import (OpenPathRequest, OpenPathResponse, ResolvedPath, ResolvePathsRequest,
                                       ResolvePathsResponse)

logger = structlog.get_logger()
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


@router.post("/sessions/{session_id}/paths/resolve", response_model=ResolvePathsResponse)
async def resolve_paths(request: Request, session_id: str, body: ResolvePathsRequest) -> ResolvePathsResponse:
    """Which of these printed paths exist. Inputs: session_id; body. Output: one answer per text, in order.

    Example: POST /api/v1/sessions/ses_1/paths/resolve {"texts": ["README.md:3"]}
      -> {"paths": [{"text": "README.md:3", "path": "/repo/README.md", "kind": "file", "line": 3}]}
    """
    cwd = await _cwd(request, session_id, "the terminal path check")

    def check() -> list[ResolvedPath]:
        out = []
        for text in body.texts:
            found = resolve(text, cwd)
            out.append(ResolvedPath(text=text, path=found.path, kind=found.kind, line=found.line) if found
                       else ResolvedPath(text=text))
        return out

    return ResolvePathsResponse(paths=await run_in_threadpool(check))


@router.post("/sessions/{session_id}/paths/open", response_model=OpenPathResponse)
async def open_path(request: Request, session_id: str, body: OpenPathRequest) -> OpenPathResponse:
    """Show a printed path in Finder or open a file in the default browser.

    Raises: HTTPException 404 (nothing by that name), 400 (a folder in the browser), 502 (``open`` failed).
    Example: POST /api/v1/sessions/ses_1/paths/open {"text": "src/a.py", "app": "finder"}
    """
    cwd = await _cwd(request, session_id, "opening a terminal path")
    found = await run_in_threadpool(resolve, body.text, cwd)
    if found is None:
        raise HTTPException(status_code=404, detail="no such file or folder")
    if body.app == "browser" and found.kind != "file":
        raise HTTPException(status_code=400, detail="a folder does not open in the browser")
    try:
        await open_app.open_path(found.path, body.app)
    except open_app.OpenFailed as exc:
        logger.warning("terminal_path_open_failed", app=body.app, error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OpenPathResponse(path=found.path, app=body.app)
