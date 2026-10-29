
from __future__ import annotations

from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _request, _via_route


async def catalog_items_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import catalog_routes

    if set(args) - {"kind", "installed_only"}:
        raise ToolError("only kind and installed_only are accepted")
    kind = args.get("kind")
    if kind is not None and not isinstance(kind, str):
        raise ToolError("kind must be a string")
    installed_only = args.get("installed_only", False)
    if not isinstance(installed_only, bool):
        raise ToolError("installed_only must be true or false")
    response = await _via_route(catalog_routes.list_catalog_items(_request(manager)))
    body = response.model_dump(mode="json")
    for key in ("items", "untrusted"):
        body[key] = [
            it for it in body[key]
            if (kind is None or it["kind"] == kind) and (not installed_only or it["installed"] is not None)
        ]
    return _ok(body)


READ_TOOLS: dict = {
    "catalog_items_list": (
        "List warez catalog items (skills, themes, plugins, mods) from the held signed index, each with featured_rank "
        "(null when not featured), first_published_at and its local install state. Optional kind and installed_only filters.",
        {"kind": {"type": "string", "description": "only this kind, such as skill, theme, plugin or mod"},
         "installed_only": {"type": "boolean", "description": "only items installed on this computer (default false)"}},
        [], catalog_items_list,
    ),
}
