
from __future__ import annotations

import json
from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.company_tools import _color_arg, _only, company_color_set
from src.core.mcp.group_tools import _group_of, _groups
from src.core.mcp.write_tools import _request, _via_route

_HEX = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$", "description": "#rrggbb"}


async def session_group_color_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_groups_routes as routes

    _only(args, "session_group_color_set", {"group", "color"})
    color = _color_arg(args)
    group = _group_of(await _groups(), args.get("group"))
    animation = getattr(group, "animation", None) or "none"
    await _via_route(routes.set_session_group_style(
        group.group_uuid, routes.StyleRequest(colour=color, gradient=None, animation=animation), _request(manager)))
    return _ok({"group": group.name, "group_uuid": group.group_uuid, "color": color})


async def layout_color_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import layouts_routes as routes
    from src.models.layouts import LayoutStyleRequest

    _only(args, "layout_color_set", {"layout", "color"})
    color = _color_arg(args)
    uuid = args.get("layout")
    if not isinstance(uuid, str) or not uuid.strip():
        raise ToolError("layout is required: a layout_uuid")
    listed = await _via_route(routes.list_layouts())
    found = next((l for l in listed.layouts if l.layout_uuid == uuid.strip()), None)
    if found is None:
        raise ToolError(f"no layout {json.dumps(uuid.strip())[:60]}")
    await _via_route(routes.set_layout_style(
        found.layout_uuid, LayoutStyleRequest(colour=color, gradient=None, animation=found.animation or "none"), _request(manager)))
    return _ok({"layout": found.layout_uuid, "name": found.name, "color": color})


READ_TOOLS: dict = {}
UNGATED_WRITES: frozenset = frozenset({"session_group_color_set", "layout_color_set"})
WRITE_TOOLS: dict = {
    "company_color_set": (
        "Color a company (company_id from companies_list) with a #rrggbb pick; it is stored as the pick's hue on the "
        "oklch wheel, so the sidebar and the Swarm family follow it. "
        "Asks the owner unless Beast Mode is armed.",
        {"company_id": {"type": "integer", "minimum": 1, "description": "company id from companies_list"}, "color": _HEX},
        ["company_id", "color"], company_color_set,
    ),
    "session_group_color_set": (
        "Give a drawer group a flat #rrggbb color (group is its group_uuid or exact name from session_groups_list). "
        "Clears a gradient, keeps the heading animation. Every open drawer repaints live.",
        {"group": {"type": "string", "description": "group_uuid or exact group name"}, "color": _HEX},
        ["group", "color"], session_group_color_set,
    ),
    "layout_color_set": (
        "Give a saved Layout a flat #rrggbb color (layout is its layout_uuid). Clears a gradient, keeps the heading "
        "animation. Every open drawer repaints live.",
        {"layout": {"type": "string", "description": "layout_uuid"}, "color": _HEX},
        ["layout", "color"], layout_color_set,
    ),
}
