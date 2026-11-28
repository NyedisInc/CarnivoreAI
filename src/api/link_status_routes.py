
from __future__ import annotations

from typing import Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.core.relay_identity.session import RelayAuthError

logger = structlog.get_logger()

router = APIRouter(tags=["phone-link"])


@router.post("/link-status/key", dependencies=[Depends(require_auth)])
async def issue_link_status_key(request: Request) -> Dict[str, str]:
    """Mint and register a link-status token for the asking phone. Raises: 404 off the link, 503 relay off, 502 relay refused."""
    if not request.scope.get("via_link"):
        raise HTTPException(status_code=404, detail="not found")
    manager = getattr(request.app.state, "phone_link", None)
    if manager is None or not manager.available:
        raise HTTPException(status_code=503, detail="mobile sync is unavailable (relay disabled)")
    try:
        return {"token": await manager.issue_status_key()}
    except RelayAuthError as exc:
        logger.info("link_status_key_failed", kind=exc.kind)
        raise HTTPException(status_code=502, detail="the relay could not register the key") from None
