
from typing import Any

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth

router = APIRouter(tags=["attention"])


@router.get("/sessions/attention", dependencies=[Depends(require_auth)])
async def attention_diagnostics(request: Request) -> dict[str, Any]:
    """Return observation age and decision metadata without capturing a pane."""
    watcher = getattr(request.app.state, "attention_watcher", None)
    return {
        "available": watcher is not None,
        "observations": watcher.diagnostics() if watcher is not None else [],
    }
