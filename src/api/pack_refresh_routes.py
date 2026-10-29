
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core.pack.span import refresh_fanout

router = APIRouter(tags=["pack"])


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: Optional[str] = Field(default=None, max_length=200)
    install: bool = False


@router.post("/pack/refresh", dependencies=[Depends(require_auth)])
async def pack_refresh(body: RefreshBody) -> Dict[str, Any]:
    """Carry a project's latest code to its replicas (``project``) and/or ask every tracking machine to refresh its install (``install``).

    Output: ``{code?: {project_uid, results}, install?: [{machine, status}]}``. Raises: 404/409 from the project sync.
    Example: POST /api/v1/pack/refresh {"project": "trader", "install": true}
    """
    return await refresh_fanout.fan_out(body.project, body.install)
