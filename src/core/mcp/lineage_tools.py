
from __future__ import annotations

from typing import Any

from src.core.mcp.bookmark_tools import _session_uuid
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, _ok
from src.core.mcp.write_tools import _via_route

MAX_MILESTONES = 40


async def session_lineage_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import lineage_routes

    session_uuid = await _session_uuid(manager, args)
    found = await _via_route(lineage_routes.lineage_of("session", session_uuid))
    data = found.model_dump()
    conversations = []
    for entry in data["timeline"]:
        marks = entry["milestones"]
        conversations.append({**entry, "milestones": marks[-MAX_MILESTONES:], "truncated": len(marks) > MAX_MILESTONES})
    return _ok({"session_uuid": session_uuid, "conversations": conversations,
                "spawned_from": [e["parent_id"] for e in data["parents"] if e["edge_kind"] == "spawned_by"],
                "spawned": [e["child_id"] for e in data["children"] if e["edge_kind"] == "spawned_by"],
                "spawn_link": data["spawn_link"], "spawn_children": data["spawn_children"]})


READ_TOOLS: dict = {
    "session_lineage_get": (
        "A session's conversations oldest first: how each began (clear, fork, rewind...), split points, milestones.",
        {"target": _TARGET_SCHEMA}, ["target"], session_lineage_get,
    ),
}
