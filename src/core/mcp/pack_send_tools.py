
from __future__ import annotations

import json
from typing import Any

from src.core.mcp import route_adapters as ra, session_target

_MACHINE = {"type": "string", "maxLength": 200, "description": "the paired computer (computers_list, detail specs)"}


def _send(call: ra.Call) -> Any:
    from src.api.pack_send_routes import SendBody

    keys = ("machine", "mode", "with_project", "wait_seconds")
    return call.route(call.session_uuid, SendBody(**{k: call.args[k] for k in keys if call.args.get(k) is not None}), call.request)


def _check(call: ra.Call) -> Any:
    from src.api.pack_send_routes import CheckBody

    return call.route(call.session_uuid, CheckBody(machine=call.args["machine"]), call.request)


SPECS = (
    ra.RouteTool(
        name="session_send", route="src.api.pack_send_routes:send_session", gate=ra.ACT,
        description="Send a running session to a paired computer. mode move: stops here, continues there. copy: a fork continues there, this keeps running. "
                    "fresh: a new agent in the same project there, no conversation. with_project adds a missing project first. Answers an op_id (pack_op_get).",
        properties={"machine": _MACHINE, "mode": {"type": "string", "enum": ["move", "copy", "fresh"]},
                    "with_project": {"type": "boolean", "description": "add the project to that computer first when it is missing (default false)"},
                    "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 3600, "description": "how long to wait for the turn to end (default 600)"}},
        required=("machine", "mode"), invoke=_send, reach=session_target.LIVE, needs_uuid=True,
        summary=lambda args, _t: f"send session {json.dumps(args.get('target'))} to {json.dumps(args.get('machine'))} as {args.get('mode')}"
                                 + (" (adding the project there first)" if args.get("with_project") else ""),
        example={"machine": "hosta", "mode": "copy", "with_project": True},
    ),
    ra.RouteTool(
        name="session_send_check", route="src.api.pack_send_routes:send_check_route", gate=ra.READ,
        description="Ask whether a running session could be sent to a paired computer, per mode (move, copy, fresh), and whether the project is already "
                    "there or can be added. Changes nothing on either computer.",
        properties={"machine": _MACHINE}, required=("machine",), invoke=_check, reach=session_target.LIVE, needs_uuid=True,
        example={"machine": "hosta"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
