
from __future__ import annotations

import json
from typing import Any

from src.core.mcp import route_adapters as ra, session_target


def _move(call: ra.Call) -> Any:
    from src.api.pack_move_routes import MoveBody

    keys = ("machine", "wait_seconds")
    return call.route(call.session_uuid, MoveBody(**{k: call.args[k] for k in keys if call.args.get(k) is not None}), call.request)


SPECS = (
    ra.RouteTool(
        name="session_move", route="src.api.pack_move_routes:move_session", gate=ra.ACT,
        description="Move a running session of this computer to a paired computer: waits for its turn to end, sleeps it, carries the "
                    "conversation and wakes it there resumed in the same conversation. The old row is archived once the new one is awake. "
                    "Answers an op_id (pack_op_get). Waits for the owner unless Beast Mode is armed.",
        properties={"machine": {"type": "string", "maxLength": 200, "description": "the paired computer to move to (pack_machines)"},
                    "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 3600, "description": "how long to wait for the turn to end (default 600)"}},
        required=("machine",), invoke=_move, reach=session_target.LIVE, needs_uuid=True,
        summary=lambda args, _t: f"move session {json.dumps(args.get('target'))} to {json.dumps(args.get('machine'))} after its turn ends",
        example={"machine": "hosta"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
