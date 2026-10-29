
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.session_groups_routes import SessionGroupsResponse, _write, list_session_groups
from src.core import session_group_store as store

router = APIRouter(prefix="/session-groups", tags=["session-groups"])


class RuleRequest(BaseModel):
    """A group's WHOLE rule; no criterion at all clears it."""

    flags: List[str] = Field(default_factory=list, description="Keys of session_group_rule.FLAGS that must all be true")
    prefix: Optional[str] = Field(default=None, description="The session name must start with this")
    suffix: Optional[str] = Field(default=None, description="The session name must end with this")


@router.put(
    "/{group_uuid}/rule",
    response_model=SessionGroupsResponse,
    dependencies=[Depends(require_auth)],
)
async def set_session_group_rule(group_uuid: str, body: RuleRequest, request: Request) -> SessionGroupsResponse:
    """Set or clear a group's dynamic rule.

    Inputs: group_uuid (str), body (RuleRequest).
    Output: SessionGroupsResponse - the whole list, like every group write.
    Raises: HTTPException 400 (``code: group_rule_invalid``), 404 (no such group), 503.
    Example: PUT /api/v1/session-groups/<uuid>/rule {"flags": ["running", "coffee"], "prefix": "api", "suffix": ""}
    """
    await _write(request, store.set_group_rule, group_uuid, body.flags, body.prefix, body.suffix)
    return await list_session_groups()
