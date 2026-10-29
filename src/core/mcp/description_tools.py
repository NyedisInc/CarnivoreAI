
from __future__ import annotations

import json
from typing import Any, Optional

from src.core.descriptions.limits import LONG_DESCRIPTION_MAX, SHORT_DESCRIPTION_MAX
from src.core.descriptions.roster import HAS_DESCRIPTION, SCOPES
from src.core.mcp import route_adapters as ra
from src.core.mcp import session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok

_SHORT_SCHEMA = {"type": "string", "maxLength": SHORT_DESCRIPTION_MAX,
                 "description": f"one line, at most {SHORT_DESCRIPTION_MAX} characters; empty clears it"}
_LONG_SCHEMA = {"type": "string", "maxLength": LONG_DESCRIPTION_MAX,
                "description": f"at most {LONG_DESCRIPTION_MAX} characters; empty clears it"}


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ToolError("project and company take an id or a name")
    return str(value)


def _roster(call: ra.Call) -> Any:
    args = call.args
    detail = args.get("detail", False)
    if not isinstance(detail, bool):
        raise ToolError("detail must be true or false")
    return call.route(call.request, scope=args.get("scope", SCOPES[0]),
                      has_description=args.get("has_description", HAS_DESCRIPTION[0]),
                      project=_text(args.get("project")), company=_text(args.get("company")), detail=detail)


def _session_description(call: ra.Call) -> Any:
    from src.models.descriptions import SessionDescriptionRequest

    body = {k: call.args[k] for k in ("short_description", "long_description") if k in call.args}
    if not body:
        raise ToolError("send short_description and/or long_description")
    if call.session_uuid is None:
        raise ToolError("that session has no stored row to describe")
    return call.route(call.request, call.session_uuid, SessionDescriptionRequest(**body))


def _session_summary(args: dict, target: Optional[session_target.SessionTarget]) -> str:
    name = (target.info.tmux_session if target is not None and target.live else
            target.tmux_name if target is not None else None) or "a session"
    parts = [f"{k.split('_')[0]} {json.dumps(args[k])}" for k in ("short_description", "long_description") if k in args]
    return f"set the description of {name}: " + ", ".join(parts)


ROSTER_PROPERTIES = {"scope": {"type": "string", "enum": list(SCOPES), "description": "roster view: online (live, default), around (live and asleep) or all (archived too)"},
                     "has_description": {"type": "string", "enum": list(HAS_DESCRIPTION), "description": "roster view: any, short, long, none or missing"},
                     "project": {"type": ["integer", "string"], "description": "roster view: project id or name"},
                     "company": {"type": ["integer", "string"], "description": "roster view: company id or name; includes every company under it"},
                     "detail": {"type": "boolean", "description": "roster view: add long descriptions"}}
ROSTER = ra.RouteTool(
    name="agents_lookup", route="src.api.descriptions_routes:get_roster", gate=ra.READ,
    description="The session roster (agents_lookup view roster).", properties=ROSTER_PROPERTIES, invoke=_roster, example={"scope": "around"},
)
ROSTER_HANDLER = ra.tables((ROSTER,))[0][ROSTER.name][3]

SPECS = (
    ra.RouteTool(
        name="session_description_set", route="src.api.descriptions_routes:set_session_description", gate=ra.ACT,
        description="Set a session's short (one line, 120 characters) and/or long (2000) description, live or "
                    "asleep, so other agents know what it is doing. Waits for the owner's approval unless Beast Mode "
                    "is armed, your own session included.",
        properties={"short_description": _SHORT_SCHEMA, "long_description": _LONG_SCHEMA},
        reach=session_target.STORED, needs_uuid=True, invoke=_session_description, summary=_session_summary,
        example={"short_description": "ships the release"},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


async def project_description_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import projects_routes
    from src.core.mcp.project_tools import _current_name, project_id_arg
    from src.core.mcp.write_tools import _via_route, park
    from src.models import UpdateProjectRequest

    extra = set(args) - {"project", "short_description", "long_description"}
    if extra:
        raise ToolError(f"project_description_set does not take {', '.join(sorted(extra))}")
    project_id = project_id_arg(args)
    fields = {k: args[k] for k in ("short_description", "long_description") if k in args}
    if not fields or not all(isinstance(v, str) for v in fields.values()):
        raise ToolError("send short_description and/or long_description as text")
    try:
        body = UpdateProjectRequest(short_description=fields.get("short_description"),
                                    description=fields.get("long_description"))
    except ValueError as exc:
        raise ToolError(f"project_description_set: {' '.join(str(exc).split())[:300]}") from exc
    name = await _current_name(project_id, include_archived=True)

    async def run(_approved: bool) -> dict:
        current = await _current_name(project_id, include_archived=True)
        row = await _via_route(projects_routes.update_project(current, body))
        return _ok({"project": {"id": row.id, "name": row.name, "short_description": row.short_description,
                                "long_description": row.description}})

    parts = [f"{k.split('_')[0]} {json.dumps(v)}" for k, v in fields.items()]
    summary = f"set the description of project {json.dumps(name)}: " + ", ".join(parts)
    return await park(manager, caller, "", "", "project_description_set", summary, {"project": project_id, **fields},
                      run, dedupe_key="project_description_set:" + json.dumps([project_id, fields], sort_keys=True))


WRITE_TOOLS["project_description_set"] = (
    "Set a project's short (one line, 120 characters) and/or long (2000) description (id from projects_list), so an "
    "agent knows what the family is for. Waits for the owner's approval unless Beast Mode is armed.",
    {"project": {"type": "integer", "minimum": 1, "description": "project id from projects_list"},
     "short_description": _SHORT_SCHEMA, "long_description": _LONG_SCHEMA},
    ["project"], project_description_set,
)
