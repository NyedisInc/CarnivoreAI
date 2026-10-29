
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.read_tools import scrub
from src.core.mcp.write_tools import _request, _via_route, park

IMPORT_ARGS = frozenset({"document", "dry_run", "apply_drawer_zone"})


def _route_request(manager: Any) -> Any:
    return SimpleNamespace(app=_request(manager).app, headers={})


async def board_export(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import board_routes

    board_id = args.get("board_id", "home")
    if not isinstance(board_id, str) or not board_id:
        raise ToolError("board_id must be the id of a stored board")
    response = await _via_route(board_routes.export_board(board_id, _route_request(manager)))
    return _ok(scrub(json.loads(response.body)))


async def board_import(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import board_routes

    unknown = sorted(set(args) - IMPORT_ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}; allowed: {', '.join(sorted(IMPORT_ARGS))}")
    document = args.get("document")
    if not isinstance(document, dict):
        raise ToolError("document is required: the parsed board file as an object")
    flags = {}
    for name in ("dry_run", "apply_drawer_zone"):
        value = args.get(name, False)
        if type(value) is not bool:
            raise ToolError(f"{name} must be true or false")
        flags[name] = value
    request = _route_request(manager)

    async def call(**extra: Any) -> dict:
        body = board_routes.ImportRequest(document=document, **{**flags, **extra})
        return await _via_route(board_routes.import_board(body, request))

    preview = (await call(dry_run=True))["preview"]
    if flags["dry_run"]:
        return _shown(preview)

    async def run(approved: bool) -> dict:
        return _ok(await call(dry_run=False))

    shown = {"board": preview["name"], "widgets": len(preview["widgets"]), "settings_for": preview["settings"],
             "replaces_drawer_area": flags["apply_drawer_zone"]}
    summary = (f"import the board '{preview['name']}' from a file ({len(preview['widgets'])} widgets; "
               f"writes settings for {len(preview['settings'])}; drawer area {'REPLACED' if flags['apply_drawer_zone'] else 'kept'}). "
               "It adds a board and replaces none.")
    key = hashlib.sha256(json.dumps([document, flags], sort_keys=True, default=str).encode()).hexdigest()
    return await park(manager, caller, "", "", "board_import", summary, shown, run, dedupe_key=key)


def _shown(preview: dict) -> dict:
    return _ok({"status": "preview", "preview": preview})


READ_TOOLS: dict = {
    "board_export": (
        "Export one Home board as a board file (its layout, the drawer widget area and the settings of the widgets it places).",
        {"board_id": {"type": "string", "description": "A stored board's id; default home."}}, [], board_export,
    ),
}
WRITE_TOOLS: dict = {
    "board_import": (
        "Add a Home board from a board file. dry_run true only previews, listing every refusal. A real import adds the "
        "board (it replaces none), writes the file's widget settings and asks the owner unless Beast Mode is armed.",
        {"document": {"type": "object"}, "dry_run": {"type": "boolean"}, "apply_drawer_zone": {"type": "boolean"}},
        ["document"], board_import,
    ),
}
