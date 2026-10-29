
from __future__ import annotations

import re
from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _via_route, park


async def pipeline_plugin_rebuild(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import pipeline_plugin_routes
    from src.core.pipeline import contract as PK
    from src.core.pipeline import registry

    plugin_id = args.get("plugin_id")
    if not isinstance(plugin_id, str) or not re.match(PK.ID_PATTERN, plugin_id):
        raise ToolError("plugin_id must be a plugin id (lowercase letters, digits, underscores)")
    if registry.find(plugin_id) is None:
        raise ToolError(f"no such plugin: {plugin_id}")

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(pipeline_plugin_routes.rebuild_plugin(plugin_id)))

    summary = (f"rebuild pipeline plugin {plugin_id}: replace its database and replay every transcript on disk "
               "(what it derived from transcripts no longer on disk is lost)")
    return await park(manager, caller, "", "", "pipeline_plugin_rebuild", summary, {"plugin_id": plugin_id}, run,
                      dedupe_key=f"pipeline_plugin_rebuild:{plugin_id}")


TOOLS: dict = {
    "pipeline_plugin_rebuild": (
        "Rebuild one save pipeline plugin: replace its database and replay every transcript on disk. Always waits "
        "for the owner's approval.",
        {"plugin_id": {"type": "string"}}, ["plugin_id"], pipeline_plugin_rebuild,
    ),
}
