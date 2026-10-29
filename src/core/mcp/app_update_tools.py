
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError

_PEER = {"peer": {"type": "string", "maxLength": 64,
                  "description": "a paired computer's key (the peer-... id computers_list gives); omit for this computer"}}


def _bare_request() -> Any:
    return SimpleNamespace(state=SimpleNamespace())


async def _status(call: ra.Call) -> Any:
    from src.api import app_update_peer_routes

    peer = call.args.get("peer")
    return await (app_update_peer_routes.computer_status(peer, _bare_request()) if peer else call.route())


async def _act(call: ra.Call) -> Any:
    from src.api import app_update_peer_routes, app_update_routes

    action, peer, enabled = call.args["action"], call.args.get("peer"), call.args.get("enabled")
    if action == "set_auto":
        if not isinstance(enabled, bool):
            raise ToolError("set_auto needs enabled: true or false")
        body = app_update_routes.AutoUpdateSetting(enabled=enabled)
        return await (app_update_peer_routes.computer_auto_update(peer, body, _bare_request()) if peer
                      else app_update_routes.set_auto_update(body))
    if enabled is not None:
        raise ToolError("enabled only goes with action set_auto")
    remote = {"check": app_update_peer_routes.computer_check, "install": app_update_peer_routes.computer_install}[action]
    local = {"check": app_update_routes.check_now, "install": app_update_routes.install_now}[action]
    return await (remote(peer, _bare_request()) if peer else local())


def _summary(args: dict, _target: Any) -> str:
    where = f"on {str(args.get('peer'))[:64]}" if args.get("peer") else "on this computer"
    if args.get("action") == "set_auto":
        return f"turn automatic app updates {'on' if args.get('enabled') else 'off'} {where}"
    return f"{args.get('action')} the Carnivore app update {where}"


SPECS = (
    ra.RouteTool(
        name="app_update_status", route="src.api.app_update_routes:get_status", gate=ra.READ,
        description="The Carnivore app's updater: state (current, available, downloading, ready, error...), running and latest "
                    "version, and the auto update switch (off unless that computer turned it on). Give peer for a paired computer; "
                    "status unsupported means its version cannot be updated remotely and needs one update by hand.",
        properties=dict(_PEER), invoke=_status, example={},
    ),
    ra.RouteTool(
        name="app_update", route="src.api.app_update_routes:check_now", gate=ra.ACT,
        description="Drive the Carnivore app updater: action check (look for a new version now), install (download if needed, "
                    "then restart into it; the computer's tmux sessions survive) or set_auto (enabled true or false). Give peer "
                    "for a paired computer, which applies its own rules.",
        properties={"action": {"type": "string", "enum": ["check", "install", "set_auto"]}, "enabled": {"type": "boolean"}, **_PEER},
        required=("action",), invoke=_act, summary=_summary, example={"action": "check"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
