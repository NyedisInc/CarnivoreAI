
from __future__ import annotations

from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _ok
from src.core.mcp.write_tools import _via_route


async def launch_profiles_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import launch_profiles_routes

    listed = await _via_route(launch_profiles_routes.list_profiles())
    return _ok({"revision": listed["revision"], "profiles": [p["summary"] for p in listed["profiles"]]})


async def launch_accounts_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import restart_account_routes

    listed = await _via_route(restart_account_routes.launch_accounts())
    return _ok({"accounts": [{"id": o.id, "name": o.name} for o in listed.options], "selected_id": listed.selected_id})


READ_TOOLS: dict = {
    "launch_profiles_list": ("The launch profiles: label, harness, account, model and a permissions badge each, with "
                             "the default of every harness flagged.", {}, [], launch_profiles_list),
    "launch_accounts_list": ("The claude accounts session_create can launch an agent on (account), and the active one "
                             "that is the default.", {}, [], launch_accounts_list),
}
