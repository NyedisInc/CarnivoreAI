
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from src.core.mcp.common import ToolError
from src.core.mcp.write_tools import _detail

FIELD = "drawer_arrangement"


async def _read(request: Any) -> tuple[int, dict]:
    from src.api import preferences_routes

    try:
        block = await preferences_routes.get_preferences(request)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc
    return int(block["revision"]), dict(block["values"].get(FIELD) or {})


async def write_pinned(request: Any, change: Callable[[list], list]) -> list:
    from src.api import preferences_routes

    for attempt in (1, 2):
        revision, arrangement = await _read(request)
        pinned = change(list(arrangement.get("pinned") or []))
        body = preferences_routes.PreferencesUpdateRequest(
            changes={FIELD: {**arrangement, "pinned": pinned}}, expected_revision=revision)
        try:
            await preferences_routes.update_preferences(request, body)
            return pinned
        except HTTPException as exc:
            if exc.status_code != 409 or attempt == 2:
                raise ToolError(_detail(exc)) from exc
    raise ToolError("the drawer arrangement kept changing; try again")
