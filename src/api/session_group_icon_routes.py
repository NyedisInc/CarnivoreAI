
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.session_groups_routes import (
    SessionGroupsResponse,
    _write,
    list_session_groups,
)
from src.core import session_group_store as store

router = APIRouter(prefix="/session-groups", tags=["session-groups"])


class IconRequest(BaseModel):
    """A group's heading icon, alone.

    ``icon`` is required so an empty body is a 422 rather than a silent
    clear; ``null`` is the explicit "no icon".
    """

    icon: Optional[str] = Field(
        ..., description="An id from client/js/icons/icon-registry.js, or null for no icon"
    )


@router.put(
    "/{group_uuid}/icon",
    response_model=SessionGroupsResponse,
    dependencies=[Depends(require_auth)],
)
async def set_session_group_icon(
    group_uuid: str, body: IconRequest, request: Request
) -> SessionGroupsResponse:
    """Set or clear a group's heading icon (issue #769).

    Description: the write behind the "icon" item in a group's kebab in
      the agents drawer. Changes the icon alone: colour, gradient,
      animation, name, membership and position are untouched. Announces
      ``sessions.changed`` reason ``groups`` like every group write, so
      every other browser repaints the heading.
    Inputs: group_uuid (str), body (IconRequest).
    Output: SessionGroupsResponse - the whole list, like every group write.
    Raises: HTTPException 400 (``code: unknown_icon``), 404 (no such
      group), 422 (no ``icon`` field), 503 (the datastore or the icon
      registry could not be read).
    Example: PUT /api/v1/session-groups/<uuid>/icon {"icon": "flask"}
      PUT /api/v1/session-groups/<uuid>/icon {"icon": null}
    """
    await _write(request, store.set_group_icon, group_uuid, body.icon)
    return await list_session_groups()
