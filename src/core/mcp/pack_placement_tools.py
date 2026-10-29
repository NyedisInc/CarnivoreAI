
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _explain(call: ra.Call) -> Any:
    from src.api.pack_placement_routes import ExplainBody

    return call.route(ExplainBody(**{k: v for k, v in call.args.items() if k != "huddle_item"}), call.request)


def _queue_list(call: ra.Call) -> Any:
    return call.route(call.request)


def _queue_cancel(call: ra.Call) -> Any:
    return call.route(int(call.args["id"]), call.request)


SPECS = (
    ra.RouteTool(
        name="placement_explain", route="src.api.pack_placement_routes:placement_explain", gate=ra.READ,
        description="Which computer in the Pack would take a job now, and why. Names every computer's headroom after its compute "
                    "reserve and any filter that ruled one out (battery, a missing tool, a restriction). Light work stays on the "
                    "project's home; heavy kinds (browser, suite, build, render) go to the most headroom. Writes nothing.",
        properties={"workload": {"type": "object", "description": "kind (light, browser, suite, build, render), est_cpu_cores, est_ram_gb, est_disk_gb"},
                    "task_type": {"type": "string", "description": "a slug; implies a kind when workload has none"},
                    "project": {"type": "string", "description": "the project's name or folder"},
                    "needs": {"type": "array", "items": {"type": "string"}, "description": "tools the job needs (playwright, python3.12, docker, node, gh)"}},
        invoke=_explain, example={"workload": {"kind": "browser"}},
    ),
    ra.RouteTool(
        name="pack_queue_items_list", route="src.api.pack_placement_routes:get_queue", gate=ra.READ,
        description="Spawn requests waiting for a computer with room in the Pack, oldest first, with the reason each last waited.",
        invoke=_queue_list, example={},
    ),
    ra.RouteTool(
        name="pack_queue_cancel", route="src.api.pack_placement_routes:delete_queue", gate=ra.ACT,
        description="Cancel one waiting spawn request (an id from pack_queue_items_list).",
        properties={"id": {"type": "integer", "minimum": 1}}, required=("id",), invoke=_queue_cancel,
        summary=lambda args, _t: f"cancel queued spawn request {args.get('id')}", example={"id": 1},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
