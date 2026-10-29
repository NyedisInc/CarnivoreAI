
from __future__ import annotations

from typing import Any

from src.core.mcp.bookmark_tools import _session_uuid
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, _ok
from src.core.mcp.write_tools import _via_route

MAX_MARKS = 200


async def session_timeline_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_timeline_routes

    session_uuid = await _session_uuid(manager, args)
    found = await _via_route(session_timeline_routes.session_timeline(session_uuid))
    data = found.model_dump()
    marks = data["marks"]
    return _ok({**data, "marks": marks[-MAX_MARKS:], "truncated": len(marks) > MAX_MARKS})


READ_TOOLS: dict = {
    "session_timeline_get": (
        "A session's timeline: conversations as bars with splits, plus compacts, bookmarks, restarts, restore points, sleeps.",
        {"target": _TARGET_SCHEMA}, ["target"], session_timeline_get,
    ),
}
