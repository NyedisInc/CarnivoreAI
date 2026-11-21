
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.codex_helpers import runtime

router = APIRouter(prefix="/agents/codex/helpers", tags=["codex-helpers"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_codex_helpers() -> Dict[str, Any]:
    """The last Codex helper check, with no I/O. Output: {armed, check}.

    ``armed`` is false before the server's boot wired the check. ``check`` carries verdict (ok, blocked, host_failed,
    not_applicable), version, binary, unapproved helper names, each helper's flag, the handshake and ``text`` (the
    readable reason when failing), or is null when nothing was checked yet.
    Example: GET /agents/codex/helpers -> {"armed": true, "check": {"verdict": "blocked", ...}}
    """
    return runtime.status()


@router.post("/check")
async def check_codex_helpers() -> Dict[str, Any]:
    """Measure the installed Codex now, off the event loop (at most a few seconds). Output: {armed, check}.

    Read only: it reads quarantine flags and sends the code-mode host one handshake; it never changes the install. A
    failing verdict raises the version's alert, a passing one resolves it.
    Example: POST /agents/codex/helpers/check -> {"armed": true, "check": {"verdict": "ok", ...}}
    """
    await asyncio.to_thread(runtime.check_now, force=True)
    return runtime.status()
