
from __future__ import annotations

import json
from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.project_colors.palette import is_hex_color, normalize_color

MAX_BULK = 200
_ALLOWED = {"project", "color", "colors"}


def _color(value: Any, label: str) -> str:
    if value == "":
        return ""
    if not is_hex_color(value):
        raise ToolError(f'{label}: color must be a #rrggbb hex or "" to remove it, got {json.dumps(value)[:40]}')
    return normalize_color(value)


def _key_to_id(key: Any, names: dict) -> int:
    text = str(key).strip()
    if text.isdigit() and int(text) in names:
        return int(text)
    matches = [pid for pid, name in names.items() if name == text]
    if not matches:
        raise ToolError(f"no project {json.dumps(text)}; see projects_list")
    if len(matches) > 1:
        raise ToolError(f"project name {json.dumps(text)} is ambiguous; use its id from projects_list")
    return matches[0]


def _plan(args: dict, names: dict) -> dict:
    if set(args) - _ALLOWED:
        raise ToolError(f"project_color_set does not take {', '.join(sorted(set(args) - _ALLOWED))}")
    colors = args.get("colors")
    if colors is not None:
        if "project" in args or "color" in args:
            raise ToolError("send project + color, or colors, not both")
        if not isinstance(colors, dict) or not colors:
            raise ToolError("colors must be a non-empty object of project -> #rrggbb (or \"\" to remove)")
        if len(colors) > MAX_BULK:
            raise ToolError(f"colors is over the {MAX_BULK} project limit")
        plan: dict = {}
        for key, value in colors.items():
            pid = _key_to_id(key, names)
            if pid in plan:
                raise ToolError(f"project {json.dumps(names[pid])} appears twice in colors")
            plan[pid] = _color(value, str(key))
        return plan
    from src.core.mcp.project_tools import project_id_arg

    pid = project_id_arg(args)
    if pid not in names:
        raise ToolError(f"no project with id {pid}; see projects_list")
    return {pid: _color(args.get("color"), f"project {pid}")}


async def project_color_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import projects_routes
    from src.core.mcp.project_tools import _names_by_id
    from src.core.mcp.write_tools import _via_route, park
    from src.models import UpdateProjectRequest

    names = await _names_by_id()
    plan = _plan(args, names)

    async def run(_approved: bool) -> dict:
        current = await _names_by_id()
        gone = [pid for pid in plan if pid not in current]
        if gone:
            raise ToolError(f"project id {gone[0]} is gone; nothing was changed")
        done = []
        for pid, color in plan.items():
            try:
                row = await _via_route(projects_routes.update_project(current[pid], UpdateProjectRequest(color=color)))
            except ToolError as exc:
                landed = ", ".join(f"{d['id']} ({json.dumps(d['name'])})" for d in done) or "none"
                raise ToolError(f"{exc}; project colors already changed: {landed}; stopped at project id {pid}") from exc
            done.append({"id": row.id, "name": row.name, "color": row.color})
        return _ok({"projects": done})

    shown = ", ".join(f"{json.dumps(names[pid])} {color or 'no color'}" for pid, color in list(plan.items())[:12])
    more = f" and {len(plan) - 12} more" if len(plan) > 12 else ""
    verb = "remove the color of" if all(c == "" for c in plan.values()) else "set the color of"
    summary = f"{verb} {len(plan)} project{'s' if len(plan) != 1 else ''}: {shown}{more}"
    return await park(manager, caller, "", "", "project_color_set", summary, {"colors": {str(p): c for p, c in plan.items()}},
                      run, dedupe_key="project_color_set:" + json.dumps(sorted(plan.items())))


READ_TOOLS: dict = {}
UNGATED_WRITES: frozenset = frozenset()
WRITE_TOOLS = {
    "project_color_set": (
        "Recolor a project, or many in one owner approval: project + color, or colors {project id or name: #rrggbb}. "
        "Empty string removes a color. Everything is validated first (a bad row refuses the call); writes then run in "
        "order and a refusal stops there, naming rows already changed. Waits for approval unless Beast Mode is armed.",
        {"project": {"type": "integer", "minimum": 1, "description": "project id from projects_list (single form)"},
         "color": {"type": "string", "pattern": "^(#[0-9a-fA-F]{6})?$", "description": "#rrggbb, or empty to remove (single form)"},
         "colors": {"type": "object", "maxProperties": MAX_BULK,
                    "additionalProperties": {"type": "string", "pattern": "^(#[0-9a-fA-F]{6})?$"},
                    "description": "bulk form: project id or exact name -> #rrggbb, or empty to remove"}},
        [], project_color_set,
    ),
}
