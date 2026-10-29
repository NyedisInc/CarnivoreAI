
from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.core.attention.diagnostics import AttentionDiagnostics

router = APIRouter(tags=["attention"])


@router.get("/sessions/attention", dependencies=[Depends(require_auth)], response_model=AttentionDiagnostics)
async def attention_diagnostics(request: Request) -> AttentionDiagnostics:
    """Return observation age and decision metadata without capturing a pane."""
    watcher = getattr(request.app.state, "attention_watcher", None)
    return AttentionDiagnostics(
        available=watcher is not None,
        observations=watcher.diagnostics() if watcher is not None else [],
    )
