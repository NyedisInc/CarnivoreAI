
from __future__ import annotations

import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from src.core.mcp import route_adapters as ra
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok

MAX_HISTORY_GROUPS = 100
MAX_HISTORY_SESSIONS = 500
DEFAULT_HISTORY_GROUPS = 25
DEFAULT_HISTORY_SESSIONS = 10
MAX_OFFSET = 100000
MAX_TEXT = 4096
PROJECT_STATES = ("all", "active", "archived")
HISTORY_SORTS = ("recent", "name", "oldest")
_ID = {"type": "integer", "minimum": 1}


def _read(**fields: Any) -> ra.RouteTool:
    return ra.RouteTool(gate=ra.READ, redact=True, **fields)


def _id(args: dict, key: str, hint: str) -> int:
    value = args.get(key)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError(f"{key} is required: the id from {hint}")
    return value


def _int(args: dict, key: str, default: int, low: int, high: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ToolError(f"{key} must be a whole number from {low} to {high}")
    return value


def _text(args: dict, key: str, *, allowed: tuple[str, ...] = ()) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT or (allowed and value not in allowed):
        raise ToolError(f"{key} must be {'one of ' + ', '.join(allowed) if allowed else 'a short string'}")
    return value


def _flag(args: dict, key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError(f"{key} must be true or false")
    return value


async def _project_name(args: dict) -> str:
    from src.core.mcp.project_tools import _current_name, project_id_arg

    return await _current_name(project_id_arg(args), include_archived=True)


def _history(call: ra.Call) -> Any:
    a = call.args
    return call.route(
        call.request, q=_text(a, "q"), state=_text(a, "state"), agent=_text(a, "agent"), since=_text(a, "since"),
        until=_text(a, "until"), project_state=_text(a, "project_state", allowed=PROJECT_STATES) or "all",
        include_empty=_flag(a, "include_empty", True), project=_text(a, "project"),
        sort=_text(a, "sort", allowed=HISTORY_SORTS) or "recent", offset=_int(a, "offset", 0, 0, MAX_OFFSET),
        limit=_int(a, "limit", DEFAULT_HISTORY_GROUPS, 1, MAX_HISTORY_GROUPS),
        session_limit=_int(a, "session_limit", DEFAULT_HISTORY_SESSIONS, 1, MAX_HISTORY_SESSIONS),
        offloaded=_flag(a, "offloaded", False), include_automated=_flag(a, "include_automated", False),
        include_conversations=_flag(a, "include_conversations", False))


async def _storage(call: ra.Call) -> Any:
    return await call.route(await _project_name(call.args))


async def _verify(call: ra.Call) -> Any:
    return await call.route(await _project_name(call.args))


async def _check_root(call: ra.Call) -> Any:
    from src.models.projects import CheckProjectRootRequest

    path = _text(call.args, "path")
    if not path or not path.strip():
        raise ToolError("path is required: the folder the project would live in")
    answer = await call.route(CheckProjectRootRequest(path=path))
    if isinstance(answer, JSONResponse):
        body = json.loads(answer.body)
        from src.core.mcp import read_tools

        text = f"{answer.status_code} {body.get('code', 'refused')}: {body.get('detail', '')}"
        raise ToolError(read_tools.scrub(text, False))
    return answer


async def _check_verify(args: dict, _target: Any) -> None:
    from src.core.mcp.project_tools import project_id_arg

    project_id_arg(args)


async def _check_accounts(args: dict, _target: Any) -> None:
    from pydantic import ValidationError

    from src.api.companies_routes import AccountsBody
    from src.core.companies import accounts

    _id(args, "company_id", "companies_list")
    pointers = args.get("accounts")
    if not isinstance(pointers, dict):
        raise ToolError("accounts must be an object: github, github_login, aws, gcp (a field left out is cleared)")
    try:
        accounts.clean_accounts(AccountsBody.model_validate(pointers).model_dump())
    except ValidationError as exc:
        raise ToolError("accounts takes only github, github_login, aws, gcp, each one line of text") from exc
    except accounts.AccountsInvalid as exc:
        raise ToolError(str(exc)) from exc


def _accounts_set(call: ra.Call) -> Any:
    from src.api.companies_routes import AccountsBody

    return call.route(_id(call.args, "company_id", "companies_list"), AccountsBody.model_validate(call.args["accounts"]))


async def _group_uuid(args: dict) -> str:
    from src.core.mcp import group_tools

    return group_tools._group_of(await group_tools._groups(), args.get("group")).group_uuid


async def _group_icon(call: ra.Call) -> Any:
    from src.api.session_group_icon_routes import IconRequest

    if "icon" not in call.args or not (call.args["icon"] is None or isinstance(call.args["icon"], str)):
        raise ToolError("icon is required: an icon id as text, or null for no icon")
    return await call.route(await _group_uuid(call.args), IconRequest(icon=call.args["icon"]), call.request)


async def _group_rule(call: ra.Call) -> Any:
    from src.api.session_group_rule_routes import RuleRequest

    flags = call.args.get("flags", [])
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise ToolError("flags must be a list of rule flag names")
    body = RuleRequest(flags=flags, prefix=_text(call.args, "prefix"), suffix=_text(call.args, "suffix"))
    return await call.route(await _group_uuid(call.args), body, call.request)


_HISTORY_PROPERTIES = {
    "q": {"type": "string", "description": "Search project name and folder, title, tmux name, agent and conversation id."},
    "state": {"type": "string", "description": "Comma list of running, asleep, closed, removed, unknown; empty is all."},
    "agent": {"type": "string", "description": "Comma list of agent families ('unknown' for none); empty is all."},
    "since": {"type": "string", "description": "ISO date or datetime: last active at or after it."},
    "until": {"type": "string", "description": "ISO date or datetime: last active at or before it."},
    "project_state": {"type": "string", "enum": list(PROJECT_STATES)},
    "include_empty": {"type": "boolean", "description": "List projects with no matching entry too. Default true."},
    "project": {"type": "string", "description": "One group only: a project id, or 'none'."},
    "sort": {"type": "string", "enum": list(HISTORY_SORTS)},
    "offset": {"type": "integer", "minimum": 0, "maximum": MAX_OFFSET},
    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_HISTORY_GROUPS, "description": "Groups per page. Default 25."},
    "session_limit": {"type": "integer", "minimum": 1, "maximum": MAX_HISTORY_SESSIONS, "description": "Rows per group. Default 10."},
    "offloaded": {"type": "boolean", "description": "Also rows whose conversation is in the backup vault."},
    "include_automated": {"type": "boolean", "description": "Also scheduler runs and headless probes."},
    "include_conversations": {"type": "boolean", "description": "Also past conversations inside one tmux session."},
}
_PROJECT = {"project": {**_ID, "description": "project id from projects_list"}}
_GROUP = {"group": {"type": "string", "description": "group_uuid or exact name from session_groups_list"}}

SPECS = (
    _read(
        name="projects_authority_get", route="src.api.projects_routes:get_projects_authority",
        invoke=lambda call: call.route(),
        description="Where the project list came from and whether project writes work: mode, writable, count, startup repairs.",
    ),
    _read(
        name="projects_presence_get", route="src.api.projects_presence_routes:get_projects_presence",
        invoke=lambda call: call.route(),
        description="Probe every project's folder now: present, missing, unreachable or unchecked, with the reason. Changes nothing.",
    ),
    _read(
        name="project_history_get", route="src.api.projects_history_routes:get_projects_history", invoke=_history,
        properties=_HISTORY_PROPERTIES, forward_query=True, example={"limit": 5},
        description="Every project with its past work, grouped and paged: search, filter by state, agent or dates. limit 1 to 100 groups.",
    ),
    _read(
        name="project_storage_get", route="src.api.project_pack_routes:get_project_storage", invoke=_storage,
        properties=_PROJECT, required=("project",), example={"project": 1},
        description="A project's pack state, job progress and the cheap archive check. project is the id from projects_list.",
    ),
    _read(
        name="project_root_check", route="src.api.projects_routes:check_project_root", invoke=_check_root,
        properties={"path": {"type": "string", "description": "The folder the project would live in."}},
        required=("path",), example={"path": "/tmp/demo"},
        description="Ask whether a folder may be a project's root, before project_create. Writes nothing; a refused folder is the error.",
    ),
    _read(
        name="company_accounts_get", route="src.api.companies_routes:get_company_accounts",
        invoke=lambda call: call.route(_id(call.args, "company_id", "companies_list")),
        properties={"company_id": {**_ID, "description": "company id from companies_list"}}, required=("company_id",),
        example={"company_id": 1},
        description="A company's account pointers (github, github_login, aws, gcp names or ids; never secrets). Empty when none are set.",
    ),
    _read(
        name="item_settings_list", route="src.api.item_settings_routes:get_item_settings", invoke=lambda call: call.route(),
        description="Every setting the owner chose for a widget or plugin, with the revision. Only choices, never defaults.",
    ),
    _read(
        name="row_looks_list", route="src.api.row_looks_routes:list_row_looks", invoke=lambda call: call.route(),
        description="The color and icon of every styled sidebar row (file, page, board), by row id.",
    ),
    ra.RouteTool(
        name="project_storage_check", route="src.api.project_pack_routes:verify_project_storage", gate=ra.ACT, invoke=_verify,
        properties=_PROJECT, required=("project",), example={"project": 1}, redact=True, precheck=_check_verify,
        summary=lambda args, _t: f"check the packed archive of project {args.get('project')} against its stored checksum "
                                 "(reads the whole archive file, changes nothing)",
        description="Hash a packed project's archive and compare it to the checksum stored when it was packed. Reads the whole file; "
                    "changes nothing. Waits for the owner's approval unless Beast Mode is armed.",
    ),
    ra.RouteTool(
        name="company_accounts_set", route="src.api.companies_routes:put_company_accounts", gate=ra.ACT, invoke=_accounts_set,
        properties={"company_id": {**_ID, "description": "company id from companies_list"},
                    "accounts": {"type": "object", "description": "github, github_login, aws, gcp: names or ids, never secrets. "
                                                                  "The whole set: a field left out is cleared."}},
        required=("company_id", "accounts"), example={"company_id": 1, "accounts": {"github": "acme"}}, redact=True,
        precheck=_check_accounts,
        summary=lambda args, _t: f"replace the account pointers of company {args.get('company_id')} with "
                                 f"{json.dumps(sorted(args.get('accounts') or {}))} (a field left out is cleared)",
        description="Replace a company's account pointers (names or ids, never secrets; a secret shaped value is refused). A field left "
                    "out is cleared. Always waits for the owner's approval.",
    ),
    ra.RouteTool(
        name="session_group_icon_set", route="src.api.session_group_icon_routes:set_session_group_icon", gate=ra.ARRANGE,
        invoke=_group_icon, redact=True,
        properties={**_GROUP, "icon": {"type": ["string", "null"], "description": "An icon id of the app's icon set, or null for none."}},
        required=("group", "icon"), example={"group": "g", "icon": None},
        description="Set or clear a drawer group's heading icon; its color, name and members are untouched.",
    ),
    ra.RouteTool(
        name="session_group_rule_set", route="src.api.session_group_rule_routes:set_session_group_rule", gate=ra.ARRANGE,
        invoke=_group_rule, redact=True,
        properties={**_GROUP, "flags": {"type": "array", "items": {"type": "string"}, "description": "Rule flags that must all be true."},
                    "prefix": {"type": "string", "description": "The name must start with this."},
                    "suffix": {"type": "string", "description": "The name must end with this."}},
        required=("group",), example={"group": "g", "flags": [], "prefix": "api"},
        description="Set a drawer group's dynamic rule (flags, name prefix, name suffix) as a whole; no criterion clears it.",
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


async def project_merge_run(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.library_cleanup_routes import MergeBody, merge_project
    from src.core.mcp.project_tools import project_label
    from src.core.mcp.write_tools import _via_route, park

    if set(args) - {"source", "into"}:
        raise ToolError("project_merge_run takes only source and into")
    source, into = _id(args, "source", "projects_list"), _id(args, "into", "projects_list")
    if source == into:
        raise ToolError("source and into are the same project")
    request = ra.route_request(manager)

    async def run(_approved: bool) -> dict:
        answer = await _via_route(merge_project(source, MergeBody(into=into, allow_different_folder=False), request))
        return _ok(jsonable_encoder(answer))

    summary = (f"MERGE project {await project_label(source, include_archived=True)} into {await project_label(into)}: its sessions and records move, "
               "then the source project row is deleted (folders on disk are untouched; two different folders are refused)")
    return await park(manager, caller, "", "", "project_merge_run", summary, {"source": source, "into": into}, run,
                      dedupe_key=f"project_merge_run:{source}:{into}")


WRITE_TOOLS["project_merge_run"] = (
    "Merge one project into another (ids from projects_list): the source's sessions and records move to the project that stays "
    "and the source row is deleted; folders on disk are untouched, two different folders are refused. Always waits for the "
    "owner's approval, even in Beast Mode.",
    {"source": {**_ID, "description": "the project that goes away"}, "into": {**_ID, "description": "the project that stays"}},
    ["source", "into"], project_merge_run,
)
