
from __future__ import annotations

import json
from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _request, _via_route, park


def _mod_id_arg(args: dict, allowed: set) -> str:
    if set(args) - allowed:
        raise ToolError(f"only {', '.join(sorted(allowed))} are accepted")
    value = args.get("mod_id")
    if not isinstance(value, str) or len(value) != 16 or any(c not in "0123456789abcdef" for c in value):
        raise ToolError("mod_id is required: the id from mods_list")
    return value


async def _entry(manager: Any, mod_id: str) -> dict:
    from src.api import mods_routes

    data = await _via_route(mods_routes.list_mods(_request(manager)))
    for mod in data["mods"]:
        if mod["mod_id"] == mod_id:
            return mod
    raise ToolError("no mod with that mod_id; see mods_list")


async def mods_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import mods_routes

    if args:
        raise ToolError("mods_list takes no arguments")
    return _ok(await _via_route(mods_routes.list_mods(_request(manager))))


async def mod_enabled_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import mods_routes
    from src.models.mods import SetEnabledRequest

    mod_id = _mod_id_arg(args, {"mod_id", "enabled"})
    if not isinstance(args.get("enabled"), bool):
        raise ToolError("enabled is required and must be true or false")
    enabled = args["enabled"]
    mod = await _entry(manager, mod_id)
    if enabled and mod["source"] == "local" and mod["registered_in"] == 0:
        raise ToolError("mod_not_registered: a local mod that no settings file lists cannot be switched on over MCP "
                        "(it has no review); the owner switches it on in the Mods page of the app")

    async def run(approved: bool) -> dict:
        row = await _via_route(mods_routes.set_mod_enabled(_request(manager), mod_id, SetEnabledRequest(enabled=enabled)))
        return _ok(row)

    summary = (f"switch {'on' if enabled else 'off'} the Claude Code mod {json.dumps(mod['name'])} at {mod['path']} "
               f"(source {mod['source']}, now {mod['state']}, listed in {mod['registered_in']} of {mod['groups_total']} "
               "settings files; edits Claude Code's settings.json files, the folder stays)")
    if enabled:
        summary += (f". WARNING: a mod is unsandboxed code that runs with your permissions in every Claude login that "
                    f"shares those {mod['groups_total']} settings file(s); local mods are not reviewed")
    return await park(manager, caller, "", "", "mod_enabled_set", summary, {"mod_id": mod_id, "enabled": enabled}, run,
                      dedupe_key=f"mod_enabled_set:{mod_id}:{enabled}")


async def mod_remove(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import mods_routes

    mod_id = _mod_id_arg(args, {"mod_id"})
    mod = await _entry(manager, mod_id)

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(mods_routes.remove_mod(_request(manager), mod_id)))

    summary = (f"remove the local Claude Code mod {json.dumps(mod['name'])} at {mod['path']}: unregister it from "
               "Claude Code's settings.json files and move the folder to the trash")
    return await park(manager, caller, "", "", "mod_remove", summary, {"mod_id": mod_id}, run,
                      dedupe_key=f"mod_remove:{mod_id}", beast_eligible=False)


_ID = {"mod_id": {"type": "string", "description": "mod id from mods_list (16 hex characters)"}}

READ_TOOLS: dict = {
    "mods_list": ("List Claude Code mods: each with mod_id, name, version, path, source (catalog or local), state (on, off or partial), "
                  "is_mod, present and removable, plus the settings-file groups and the claude version gate.", {}, [], mods_list),
}

WRITE_TOOLS: dict = {
    "mod_enabled_set": ("Switch a Claude Code mod on or off in every Claude settings.json (the folder stays). Asks the owner unless Beast Mode is armed.",
                        {**_ID, "enabled": {"type": "boolean"}}, ["mod_id", "enabled"], mod_enabled_set),
    "mod_remove": ("Remove a LOCAL Claude Code mod (a folder under ~/.claude/mods the catalog did not install): unregister it and move "
                   "it to the trash. Always waits for the owner's approval.", _ID, ["mod_id"], mod_remove),
}
