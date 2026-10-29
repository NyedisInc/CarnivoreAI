
from __future__ import annotations

import json
from typing import Any

from fastapi.encoders import jsonable_encoder

from src.core.mcp import route_adapters as ra
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok


def _create(call: ra.Call) -> Any:
    from src.models.projects import CreateProjectRequest

    return call.route(CreateProjectRequest(**{k: call.args[k] for k in ("name", "path", "description") if k in call.args}))


def _create_summary(args: dict, _target: Any) -> str:
    return f"create project {json.dumps(args.get('name'))} in {json.dumps(args.get('path'))}"


SPECS = (
    ra.RouteTool(
        name="project_create", route="src.api.projects_routes:create_project", gate=ra.ACT,
        description="Add a project: a display name and an existing folder (path), optional description. Waits for the "
                    "owner's approval unless Beast Mode is armed.",
        properties={"name": {"type": "string"}, "path": {"type": "string"}, "description": {"type": "string"}},
        required=("name", "path"), invoke=_create, summary=_create_summary,
        example={"name": "demo", "path": "/tmp/demo"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


async def project_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import projects_routes
    from src.core.mcp.project_tools import _current_name, project_id_arg
    from src.core.mcp.write_tools import _via_route, park

    if set(args) - {"project"}:
        raise ToolError("project_delete takes only project")
    project_id = project_id_arg(args)
    name = await _current_name(project_id, include_archived=True)
    request = ra.route_request(manager)

    async def run(_approved: bool) -> dict:
        current = await _current_name(project_id, include_archived=True)
        answer = await _via_route(projects_routes.delete_project(current, request))
        return _ok({"deleted": True, "project": {"id": project_id, "name": current}, "detail": jsonable_encoder(answer)})

    summary = (f"DELETE project {json.dumps(name)} for good: its agents are turned off and its row is deleted "
               "(the folder on disk is kept)")
    return await park(manager, caller, "", "", "project_delete", summary, {"project": project_id}, run,
                      dedupe_key=f"project_delete:{project_id}")


WRITE_TOOLS["project_delete"] = (
    "Delete a project for good (id from projects_list): its agents are turned off and its row deleted; the folder on "
    "disk is kept. Always waits for the owner's approval, even in Beast Mode.",
    {"project": {"type": "integer"}}, ["project"], project_delete,
)
