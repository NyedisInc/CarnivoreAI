
from __future__ import annotations

from typing import Any, Callable, Dict

from src.core.mcp import route_adapters as ra

_ID = {"id": {"type": "string", "maxLength": 64, "description": "the plugin id, from plugins_list"}}
_LIMIT = {"limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}}
_DEFAULT_LIMIT = 100


def _by_id(call: ra.Call) -> Any:
    return call.route(call.args["id"], call.request)


def _rows(call: ra.Call) -> Any:
    return call.route(call.args["id"], call.request, limit=call.args.get("limit", _DEFAULT_LIMIT))


def _summary(verb: str) -> Callable[[Dict[str, Any], Any], str]:
    return lambda args, _target: f"{verb} the plugin {str(args.get('id'))[:64]}"


SPECS = (
    ra.RouteTool(
        name="plugin_restart", route="src.cplugs.host.routes:restart_cplug", gate=ra.ACT,
        description="Restart a sidecar plugin that is already on: stop its process and start it from its code and grants as they are "
                    "now. Refused when it is off or changed since the owner approved it; never turns one on. Always waits for the owner.",
        properties=_ID, required=("id",), invoke=_by_id, summary=_summary("restart"), example={"id": "clock"},
    ),
    ra.RouteTool(
        name="plugin_stop", route="src.cplugs.host.routes:kill_cplug", gate=ra.ACT,
        description="Stop a sidecar plugin's process now (SIGKILL of its process group). It stays on, with its data and grants, "
                    "until restarted. Always waits for the owner.",
        properties=_ID, required=("id",), invoke=_by_id, summary=_summary("stop"), example={"id": "clock"},
    ),
    ra.RouteTool(
        name="plugin_capability_calls_list", route="src.cplugs.host.routes:get_activity", gate=ra.READ,
        description="List the newest capability calls one plugin made (method, outcome, time), newest first. Never a query, text or secret.",
        properties={**_ID, **_LIMIT}, required=("id",), invoke=_rows, example={"id": "clock"},
    ),
    ra.RouteTool(
        name="plugin_requests_list", route="src.cplugs.host.net_routes:get_egress", gate=ra.READ,
        description="List one plugin's recent outbound network requests and refusals: host, method, permission, status, bytes, time.",
        properties={**_ID, **_LIMIT}, required=("id",), invoke=_rows, example={"id": "clock"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
