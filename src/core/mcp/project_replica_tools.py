
from __future__ import annotations

import json
from typing import Any

from src.core.mcp import route_adapters as ra

_NAME = {"project": {"type": "string", "description": "the project's display name (projects_list)"}}


def _list(call: ra.Call) -> Any:
    return call.route(call.args["project"])


def _add(call: ra.Call) -> Any:
    from src.models.projects import AddReplicaRequest

    body = {k: call.args[k] for k in ("machine", "root", "transport") if k in call.args}
    return call.route(call.args["project"], AddReplicaRequest(**body))


def _remove(call: ra.Call) -> Any:
    return call.route(call.args["project"], call.args["machine"])


def _air_gap(call: ra.Call) -> Any:
    from src.models.projects import SetAirGapRequest

    return call.route(call.args["project"], SetAirGapRequest(air_gap=bool(call.args["air_gap"])))


def _add_summary(args: dict, _target: Any) -> str:
    return f"make an active replica of project {json.dumps(args.get('project'))} on {json.dumps(args.get('machine'))}"


def _remove_summary(args: dict, _target: Any) -> str:
    return f"remove the replica of project {json.dumps(args.get('project'))} on {json.dumps(args.get('machine'))}"


def _air_gap_summary(args: dict, _target: Any) -> str:
    state = "on" if args.get("air_gap") else "off"
    return f"turn air-gap {state} for project {json.dumps(args.get('project'))}"


SPECS = (
    ra.RouteTool(
        name="project_replica_list", route="src.api.project_replica_routes:list_project_replicas", gate=ra.READ,
        description="A project's stable uid, its Pack state and the paired computers holding an active replica of it.",
        properties=dict(_NAME), required=("project",), invoke=_list, example={"project": "demo"},
    ),
    ra.RouteTool(
        name="project_replica_add", route="src.api.project_replica_routes:add_project_replica", gate=ra.ACT,
        description="Make an ACTIVE replica of a project on a paired computer, under the same uid (identity only; code "
                    "moves by the transport). Waits for the owner's approval unless Beast Mode is armed.",
        properties={**_NAME, "machine": {"type": "string"}, "root": {"type": "string"}, "transport": {"type": "string"}},
        required=("project", "machine"), invoke=_add, summary=_add_summary,
        example={"project": "demo", "machine": "studio"},
    ),
    ra.RouteTool(
        name="project_replica_remove", route="src.api.project_replica_routes:remove_project_replica", gate=ra.ACT,
        description="Stop a paired computer being a replica of a project: it keeps its folder and project as an ordinary "
                    "one. Waits for the owner's approval unless Beast Mode is armed.",
        properties={**_NAME, "machine": {"type": "string"}}, required=("project", "machine"), invoke=_remove,
        summary=_remove_summary, example={"project": "demo", "machine": "studio"},
    ),
    ra.RouteTool(
        name="project_air_gap_set", route="src.api.project_replica_routes:set_project_air_gap", gate=ra.ACT,
        description="Turn a project's air-gap on or off: on means Carnivore never contacts GitHub for it. Waits for the "
                    "owner's approval unless Beast Mode is armed.",
        properties={**_NAME, "air_gap": {"type": "boolean"}}, required=("project", "air_gap"), invoke=_air_gap,
        summary=_air_gap_summary, example={"project": "demo", "air_gap": True},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
