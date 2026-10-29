
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.core.notifications import links

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


@router.get("/link")
async def get_link(request: Request) -> Dict[str, str]:
    """The link-back kind in use. Output: {kind, base, reason}; ``reason`` is a stable code, never prose."""
    manager = getattr(request.app.state, "phone_link", None)
    result = await links.resolver.resolve(manager)
    return {"kind": result.kind, "base": result.base, "reason": result.reason}
