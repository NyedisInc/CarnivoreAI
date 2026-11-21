
from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.federation_pack_transport_routes import _peer_only
from src.api.peer_auth import Principal, require_peer
from src.core.pack.jobs import copies
from src.core.pack.machines import capabilities as pack_capabilities

router = APIRouter(prefix="/federation/pack/jobs", tags=["federation"])
_require_replica = require_peer("replica")

CAP_FORGET_COPY = "pack.jobs.forget_copy"
pack_capabilities.register(CAP_FORGET_COPY)


class ForgetCopyBody(BaseModel):
    """Which copy, the home's tips, and whether to only look. ``tips`` are 40 or 64 hex shas, never paths."""

    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=8, max_length=64)
    tips: List[str] = Field(default_factory=list, max_length=5000)
    dry_run: bool = True

    @field_validator("tips")
    @classmethod
    def _shas(cls, tips: List[str]) -> List[str]:
        if any(not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", t) for t in tips):
            raise ValueError("every tip must be a 40 or 64 character hex sha")
        return tips


@router.post("/forget-copy")
async def forget_copy(body: ForgetCopyBody, principal: Principal = Depends(_require_replica)) -> Dict[str, Any]:
    """Check this computer's copy and, unless ``dry_run``, move it to the Trash after every check passes again.

    Inputs: body (ForgetCopyBody). Output: {verdict: deletable | deleted | kept, code, root, ignored, ignored_more}; a copy that is not
      the caller's, has no made-copy record or fails a check is ``kept`` with its code (never an error).
    Raises: HTTPException 403 not a peer, 422 a tip that is not a sha.
    """
    caller = _peer_only(principal)
    if body.dry_run:
        verdict = await run_in_threadpool(copies.check, body.project_uid, caller, body.tips)
    else:
        verdict = await run_in_threadpool(copies.forget, body.project_uid, caller, body.tips)
    return verdict.wire()
