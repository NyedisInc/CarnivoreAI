
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from types import SimpleNamespace
from typing import Any, Dict, Optional

from src.core.automations import models as m
from src.core.automations import contract, schedule
from src.core.mcp import pending
from src.core.mcp.approvals import diff as approval_diff
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _request, _via_route, park

_ID = {"type": "string", "description": "automation id (aut_...) from automations_list"}
_RUN = {"type": "string", "description": "run id (run_...) from automation_runs_list"}
_TARGET = {"type": "object", "description": (
    "kind and its fields: blueprint_launch, recipe (a report, or a system action: sleep_idle_sessions, restart_session, send_notification, "
    "backup_health_check; params per action), swarm_card, agent, session_message (session_uuid, text, if_asleep, if_gone, project_id), command "
    "(command: exact text from automation_commands_get, optional project_id) or sequence (steps: 2 to 4 targets). automations_list shows examples")}
_DELIVERY = {"type": "object", "description": "notify (bool) and notify_on (always, failure or report)"}
_CONTRACT_PROPS = {
    "description": {"type": "string", "maxLength": 500, "description": "what the automation is for"},
    "project_id": {"type": ["integer", "null"], "minimum": 1, "description": "project it belongs to, or null"},
    "misfire": {"type": "string", "enum": ["skip", "run_once"], "description": "missed slots: skip them or run once on return"},
    "retry_max": {"type": "integer", "minimum": 0, "maximum": 3, "description": "retries after a failure (not for plan-spending targets)"},
    "retry_backoff_s": {"type": "integer", "minimum": 60, "maximum": 3600, "description": "seconds before a retry"},
    "max_runtime_s": {"type": ["integer", "null"], "minimum": 60, "maximum": 86400, "description": "cap on one run, or null"},
}
_CONTRACT_KEYS = {"description", "project_id", "misfire", "retry_max", "retry_backoff_s", "max_runtime_s"}
_CREATE_KEYS = {"name", "cron", "target", "delivery", "enabled"} | _CONTRACT_KEYS
_LIST_KEYS = {"project_id", "session", "enabled", "target_kind", "group_by"}
_UPDATE_KEYS = {"automation_id", "revision", "name", "cron", "target", "delivery", "enabled"} | _CONTRACT_KEYS


def _only(args: dict, allowed: set, tool: str) -> None:
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError(f"{tool} does not take: {', '.join(extra)}")


def _text(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} is required and must be non-empty text")
    return value.strip()


def _unattended_refusal(args: dict) -> Optional[dict]:
    target = args.get("target")
    if "acknowledge_unattended" in args or (isinstance(target, dict) and target.get("permission") == "unattended"):
        return pending.refused_result("running with no permission prompts needs the owner to type the phrase in the app; it cannot be set over MCP")
    return None


def _precheck(args: dict) -> None:
    try:
        if "cron" in args:
            schedule.compile_cron(_text(args, "cron"), time.time())
        if "target" in args:
            m.validate_target(args["target"])
        if "delivery" in args:
            m.validate_delivery(args["delivery"])
    except m.AutomationInvalid as exc:
        raise ToolError(f"{exc.code}: {str(exc)[:200]}") from exc


def _mcp_request(manager: Any, caller: AgentCaller) -> Any:
    who = contract.actor("mcp", session_id=caller.current_session_id or caller.session_id, tmux=caller.tmux_name,
                         client=caller.token_name)
    return SimpleNamespace(app=_request(manager).app, automation_actor=who)


async def _stored(manager: Any, automation_id: str, revision: Optional[int] = None) -> Dict[str, Any]:
    store = getattr(getattr(_request(manager).app, "state", None), "automation_store", None)
    if store is None:
        raise ToolError("automations_unavailable")
    try:
        row = await asyncio.to_thread(store.get, automation_id)
    except m.AutomationNotFound as exc:
        raise ToolError(f"not_found: no automation {automation_id}") from exc
    if revision is not None and row["revision"] != revision:
        raise ToolError(f"revision_conflict: {automation_id} is at revision {row['revision']}; read it again (automation_get)")
    return row


def _key(tool: str, args: dict) -> str:
    return f"{tool}:{hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()}"


async def automations_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, _LIST_KEYS, "automations_list")
    project_id, enabled = args.get("project_id", 0), args.get("enabled")
    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 0:
        raise ToolError("project_id must be a project row id")
    if enabled is not None and not isinstance(enabled, bool):
        raise ToolError("enabled must be true or false")
    for key in ("session", "target_kind", "group_by"):
        if args.get(key) is not None and (not isinstance(args[key], str) or not args[key].strip()):
            raise ToolError(f"{key} must be non-empty text")
    text = {k: (args[k].strip() if args.get(k) is not None else None) for k in ("session", "target_kind", "group_by")}
    return _ok(await _via_route(automation_routes.list_automations(_request(manager), project_id, text["session"], enabled,
                                                                   text["target_kind"], text["group_by"])))


async def automation_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, {"automation_id"}, "automation_get")
    return _ok(await _via_route(automation_routes.get_automation(_request(manager), _text(args, "automation_id"))))


async def automation_runs_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, {"automation_id", "before", "limit"}, "automation_runs_list")
    limit = args.get("limit", 20)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ToolError("limit must be a whole number from 1 to 50")
    before = args.get("before") or ""
    if not isinstance(before, str):
        raise ToolError("before must be a run id")
    if not args.get("automation_id"):
        return _ok(await _via_route(automation_routes.list_recent_runs(_request(manager), before, limit)))
    return _ok(await _via_route(automation_routes.list_runs(_request(manager), _text(args, "automation_id"), before, limit)))


async def automation_run_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_run_routes

    _only(args, {"run_id"}, "automation_run_get")
    return _ok(await _via_route(automation_run_routes.get_run(_request(manager), _text(args, "run_id"))))


async def automation_create(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes
    from src.models.automations import AutomationCreate

    _only(args, _CREATE_KEYS | {"acknowledge_unattended"}, "automation_create")
    if (refused := _unattended_refusal(args)) is not None:
        return refused
    _text(args, "name"), _text(args, "cron")
    if not isinstance(args.get("target"), dict):
        raise ToolError("target is required: an object with a kind")
    _precheck(args)
    request = _mcp_request(manager, caller)
    shown = {**args, "diff": approval_diff.for_create(args)}

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_routes.create_automation(request, AutomationCreate(**args))))

    return await park(manager, caller, "", "", "automation_create", f"create automation {json.dumps(args['name'])}", shown, run,
                      dedupe_key=_key("automation_create", args))


async def automation_update(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes
    from src.models.automations import AutomationPatch

    _only(args, _UPDATE_KEYS | {"acknowledge_unattended"}, "automation_update")
    if (refused := _unattended_refusal(args)) is not None:
        return refused
    automation_id = _text(args, "automation_id")
    if len(args) < 3:
        raise ToolError("automation_update needs at least one field to change")
    _precheck(args)
    request = _mcp_request(manager, caller)
    patch = {k: v for k, v in args.items() if k != "automation_id"}
    before = await _stored(manager, automation_id, args.get("revision"))
    shown = {**args, "automation": before["name"], "diff": approval_diff.for_update(before, patch)}

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_routes.update_automation(request, automation_id, AutomationPatch(**patch))))

    return await park(manager, caller, "", "", "automation_update", f"edit automation {json.dumps(before['name'])}", shown, run,
                      dedupe_key=_key("automation_update", args))


async def automation_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, {"automation_id"}, "automation_delete")
    automation_id = _text(args, "automation_id")
    request = _mcp_request(manager, caller)
    before = await _stored(manager, automation_id)
    shown = {**args, "automation": before["name"], "diff": approval_diff.for_delete(before)}

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_routes.delete_automation(request, automation_id)))

    return await park(manager, caller, "", "", "automation_delete", f"delete automation {json.dumps(before['name'])}", shown, run,
                      dedupe_key=_key("automation_delete", args), beast_eligible=False)


async def automation_run_now(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, {"automation_id"}, "automation_run_now")
    automation_id = _text(args, "automation_id")
    request = _mcp_request(manager, caller)

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_routes.run_automation_now(request, automation_id)))

    return await park(manager, caller, "", "", "automation_run_now", f"run automation {automation_id} now", args, run,
                      dedupe_key=_key("automation_run_now", args))


async def automation_run_cancel(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_run_routes

    _only(args, {"run_id"}, "automation_run_cancel")
    run_id = _text(args, "run_id")
    request = _request(manager)

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_run_routes.cancel_run(request, run_id)))

    return await park(manager, caller, "", "", "automation_run_cancel", f"cancel run {run_id}", args, run,
                      dedupe_key=_key("automation_run_cancel", args))


async def automation_finding_fix(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_run_routes

    _only(args, {"run_id", "finding_id"}, "automation_finding_fix")
    run_id, finding_id = _text(args, "run_id"), _text(args, "finding_id")
    request = _request(manager)

    async def run(approved: bool) -> dict:
        session = await _via_route(automation_run_routes.start_fix_session(request, run_id, finding_id))
        return _ok({"id": session.id, "working_dir": session.working_dir})

    return await park(manager, caller, "", "", "automation_finding_fix", f"open a fix session for finding {finding_id} of run {run_id}",
                      args, run, dedupe_key=_key("automation_finding_fix", args))


async def automation_run_continue(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_run_routes

    _only(args, {"run_id"}, "automation_run_continue")
    run_id = _text(args, "run_id")
    request = _request(manager)

    async def run(approved: bool) -> dict:
        session = await _via_route(automation_run_routes.continue_run_in_session(request, run_id))
        return _ok({"id": session.id, "working_dir": session.working_dir})

    return await park(manager, caller, "", "", "automation_run_continue", f"continue run {run_id} in a session", args, run,
                      dedupe_key=_key("automation_run_continue", args))


async def automation_log(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_log_routes

    _only(args, {"automation_id", "limit"}, "automation_log")
    limit = args.get("limit", 50)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ToolError("limit must be a whole number from 1 to 200")
    automation_id = args.get("automation_id") or None
    if automation_id is not None and not isinstance(automation_id, str):
        raise ToolError("automation_id must be an automation id")
    return _ok(await _via_route(automation_log_routes.read_log(automation_id, limit)))


async def automation_log_settings_update(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from pydantic import ValidationError

    from src.api import automation_log_routes
    from src.core.automations import scheduler_log

    _only(args, {"rotate", "max_mb", "keep"}, "automation_log_settings_update")
    try:
        body = scheduler_log.LogSettings.model_validate({**scheduler_log.LOG.settings.model_dump(), **args})
    except ValidationError as exc:
        raise ToolError(f"invalid log settings: {exc.error_count()} problem(s)") from exc

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_log_routes.put_log_settings(body)))

    return await park(manager, caller, "", "", "automation_log_settings_update",
                      f"rotate the scheduler log {body.rotate}" + (f" at {body.max_mb} MB" if body.rotate == "size" else "")
                      + f", keeping {body.keep} files", args, run, dedupe_key=_key("automation_log_settings_update", args))


async def automation_changes(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, {"automation_id", "before", "limit"}, "automation_changes")
    limit, before = args.get("limit", 20), args.get("before", 0)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ToolError("limit must be a whole number from 1 to 100")
    if isinstance(before, bool) or not isinstance(before, int) or before < 0:
        raise ToolError("before must be a change seq")
    return _ok(await _via_route(automation_routes.list_changes(_request(manager), _text(args, "automation_id"), before, limit)))


async def automation_commands_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_command_routes

    _only(args, set(), "automation_commands_get")
    return _ok(await _via_route(automation_command_routes.get_commands()))


async def automation_commands_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_command_routes
    from src.core.automations import command_allowlist

    _only(args, {"commands"}, "automation_commands_set")
    try:
        body = automation_command_routes.CommandList(commands=args.get("commands"))
        wanted = command_allowlist.clean_list(body.commands)
    except (ValueError, command_allowlist.CommandListInvalid) as exc:
        raise ToolError(f"invalid commands: {str(exc)[:200]}") from exc

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_command_routes.put_commands(automation_command_routes.CommandList(commands=wanted))))

    shown = "; ".join(wanted) if wanted else "none"
    return await park(manager, caller, "", "", "automation_commands_set",
                      f"set the commands a schedule may run to: {shown}"[:400], {"commands": wanted}, run,
                      dedupe_key=_key("automation_commands_set", {"commands": wanted}))


async def automation_scheduler_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, set(), "automation_scheduler_get")
    return _ok(await _via_route(automation_routes.get_scheduler_state()))


async def automation_scheduler_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import automation_routes

    _only(args, {"paused"}, "automation_scheduler_set")
    paused = args.get("paused")
    if not isinstance(paused, bool):
        raise ToolError("paused must be true or false")

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(automation_routes.put_scheduler_state(automation_routes.SchedulerPause(paused=paused))))

    return await park(manager, caller, "", "", "automation_scheduler_set",
                      "pause every scheduled automation run" if paused else "resume scheduled automation runs", args, run,
                      dedupe_key=_key("automation_scheduler_set", args))


READ_TOOLS: Dict[str, tuple] = {
    "automations_list": ("List the saved automations with next fire and last run. Filters (all optional, ANDed): project_id; session (id, tmux name or "
                         "session_uuid: automations aimed at it or in its project); enabled; target_kind. group_by session returns the files-under tree (rows carry files_under too).",
                         {"project_id": {"type": "integer", "minimum": 1}, "session": {"type": "string"}, "enabled": {"type": "boolean"},
                          "target_kind": {"type": "string", "enum": list(m.TARGET_KINDS)}, "group_by": {"type": "string", "enum": ["session"]}},
                         [], automations_list),
    "automation_get": ("Get one automation by id: its definition (name, cron schedule, target, delivery, enabled). Find ids with automations_list.", {"automation_id": _ID}, ["automation_id"], automation_get),
    "automation_runs_list": ("Run history, newest first, without reports (page with before): one automation's with automation_id, else every automation's, live runs included, each with its automation_name.",
                             {"automation_id": _ID, "before": _RUN, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                             [], automation_runs_list),
    "automation_run_get": ("Get one automation run by run_id with its full report, which automation_runs_list leaves out. Find run ids with automation_runs_list.", {"run_id": _RUN}, ["run_id"], automation_run_get),
    "automation_log": ("The scheduler's own log, newest first: scheduled, claimed, started, queued, delivered, finished, failed, retried, "
                       "skipped (with the reason), catch-up, and who created, edited or deleted an automation. No message texts or command output.",
                       {"automation_id": _ID, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, [], automation_log),
    "automation_changes": ("An automation's change log, newest first: who created, edited or deleted it (the app, the seed, or which agent) and the fields that moved. Page with before (a seq).",
                           {"automation_id": _ID, "before": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                           ["automation_id"], automation_changes),
    "automation_commands_get": ("The command allow-list: the exact command lines a command automation may run. Empty until the owner adds some.",
                                {}, [], automation_commands_get),
    "automation_scheduler_get": ("Whether the scheduler is paused (paused: true holds every scheduled run; run now still runs).",
                                 {}, [], automation_scheduler_get),
}

WRITE_TOOLS_MAP: Dict[str, tuple] = {
    "automation_create": ("Save an automation (a cron plus one target). Asks the owner unless Beast Mode is armed. A cron agent that runs with no permission "
                          "prompts cannot be set over MCP.",
                          {"name": {"type": "string"}, "cron": {"type": "string"}, "target": _TARGET, "delivery": _DELIVERY,
                           "enabled": {"type": "boolean"}, **_CONTRACT_PROPS}, ["name", "cron", "target"], automation_create),
    "automation_update": ("Edit an automation at the revision you read (409 if it moved). Asks the owner unless Beast Mode is armed; cannot raise an agent to unattended.",
                          {"automation_id": _ID, "revision": {"type": "integer", "minimum": 1}, "name": {"type": "string"}, "cron": {"type": "string"},
                           "target": _TARGET, "delivery": _DELIVERY, "enabled": {"type": "boolean"}, **_CONTRACT_PROPS},
                          ["automation_id", "revision"], automation_update),
    "automation_delete": ("Delete an automation and its run history. Always waits for the owner's approval.", {"automation_id": _ID}, ["automation_id"], automation_delete),
    "automation_run_now": ("Run an automation now, outside its schedule. Asks the owner unless Beast Mode is armed.", {"automation_id": _ID}, ["automation_id"], automation_run_now),
    "automation_run_cancel": ("Cancel a live automation run. Asks the owner unless Beast Mode is armed.", {"run_id": _RUN}, ["run_id"], automation_run_cancel),
    "automation_log_settings_update": ("Set how the scheduler log rotates: by size (max_mb) or daily, keeping keep old files. Asks the owner unless Beast Mode is armed.",
                                       {"rotate": {"type": "string", "enum": ["size", "daily"]}, "max_mb": {"type": "integer", "minimum": 1, "maximum": 500},
                                        "keep": {"type": "integer", "minimum": 1, "maximum": 50}}, [], automation_log_settings_update),
    "automation_commands_set": ("Replace the command allow-list (the whole list, each entry an absolute program path plus arguments, run with no shell). "
                                "Asks the owner unless Beast Mode is armed.",
                                {"commands": {"type": "array", "items": {"type": "string"}}}, ["commands"], automation_commands_set),
    "automation_scheduler_set": ("Pause (paused true) or resume (false) every scheduled automation run; no automation's own switch changes. "
                                 "Asks the owner unless Beast Mode is armed.",
                                 {"paused": {"type": "boolean"}}, ["paused"], automation_scheduler_set),
    "automation_finding_fix": ("Open a Claude session in a Scrooge finding's project with that finding's fix prompt loaded. Asks the owner unless Beast Mode is armed.",
                               {"run_id": _RUN, "finding_id": {"type": "string"}}, ["run_id", "finding_id"], automation_finding_fix),
    "automation_run_continue": ("Open a Claude session resuming a cron agent run's conversation, in the agent's folder and login. Asks the owner unless Beast Mode is armed.",
                                {"run_id": _RUN}, ["run_id"], automation_run_continue),
}

WRITE_TOOLS = frozenset(WRITE_TOOLS_MAP)
TOOLS: Dict[str, tuple] = {**READ_TOOLS, **WRITE_TOOLS_MAP}
