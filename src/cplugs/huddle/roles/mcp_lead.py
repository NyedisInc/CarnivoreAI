
from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple

from src.cplugs.huddle import service
from src.cplugs.huddle.roles import port as roles_port, retrofit, service as roles_service, set_lead
from src.cplugs.sdk import CplugContext, ToolError
from src.cplugs.sdk.definition import ToolSpec
from src.cplugs.sdk.swarm import SwarmError
from src.cplugs.sdk.tools import AgentCaller, tool_result

_SKIP = {"type": "array", "items": {"type": "string"}, "maxItems": 100, "description": "Project names or ids to leave alone."}
_PICKS = {"type": "object", "additionalProperties": {"type": "string"}, "maxProperties": 100,
          "description": "{project name or id: session name or stable key} to promote INSTEAD of the project's current lead."}


def _unknown(args: dict, allowed: set) -> None:
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError(f"unknown argument(s): {', '.join(extra)}")


def _lists(args: dict) -> Tuple[list, dict]:
    skip, picks = args.get("skip") or [], args.get("picks") or {}
    if not isinstance(skip, list) or not all(isinstance(s, str) for s in skip) or not isinstance(picks, dict) \
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in picks.items()):
        raise ToolError("skip is a list of project names or ids, and picks maps a project to a session name or key")
    return skip, picks


async def huddle_leads_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    _unknown(args, {"skip", "picks"})
    skip, picks = _lists(args)
    try:
        return tool_result({"plan": await retrofit.plan(roles_port.session_ctx(ctx), skip, picks)})
    except roles_service.RolesUnmeasured as exc:
        raise ToolError(f"could not read the sessions: {exc}") from exc


async def _retrofit_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    _unknown(args, {"skip", "picks"})
    skip, picks = _lists(args)
    try:
        rows = await retrofit.plan(roles_port.session_ctx(ctx), skip, picks)
    except roles_service.RolesUnmeasured as exc:
        raise ToolError(f"could not read the sessions: {exc}") from exc
    promoted = [r for r in rows if r["action"] in (retrofit.PROMOTE, retrofit.PROMOTE_COMPANY)]
    todo = [f"{r['project']}: {r['session_name']}" for r in promoted]
    running = [f"{r['project']}: {r['session_name']}" for r in promoted if r.get("state") == "live"]
    if not todo:
        return {"skip": skip, "picks": picks}, "promote nothing (no project has a lead to promote)"
    stopped = ("; STOPPED AND RESUMED (running now): " + "; ".join(running)) if running else "; none is running, so none is stopped"
    return {"skip": skip, "picks": picks}, f"promote {len(todo)} lead session(s) to project agents: " + "; ".join(todo) + stopped


async def huddle_leads_update(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    skip, picks = _lists(args)
    try:
        done = await retrofit.run(roles_port.session_ctx(ctx), skip, picks, dry_run=False)
    except (roles_service.RolesUnmeasured, SwarmError) as exc:
        raise ToolError(f"the retrofit stopped: {exc}") from exc
    roles_port.announce(ctx)
    return tool_result(done)


async def _lead_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    _unknown(args, {"list", "session", "agent", "seat_only"})
    key, session = args.get("list"), args.get("session")
    agent, seat_only = args.get("agent", False), args.get("seat_only", False)
    if not isinstance(key, str) or not key.isdigit() or (session is not None and not isinstance(session, str)) \
            or not isinstance(agent, bool) or not isinstance(seat_only, bool):
        raise ToolError("list is a project id, session a stable key (or null to empty the seat), agent and seat_only true or false")
    if agent and seat_only:
        raise ToolError("seat_only leaves the Swarm agent alone, so it cannot be combined with agent true")
    names = await asyncio.to_thread(service.project_names, ctx)
    if key not in names:
        raise ToolError(f"no project {key}")
    if seat_only:
        what = "release the pinned Task Manager seat" if session is None else f"pin the Task Manager seat to session {session}, leaving the Swarm agent alone,"
    else:
        what = "empty the lead seat" if session is None else f"make session {session} the lead" + (" and the project agent" if agent else "")
    return {"list": key, "session": session, "agent": agent, "seat_only": seat_only}, f"{what} of {names[key]}"


async def huddle_lead_set(ctx: CplugContext, caller: AgentCaller, args: dict) -> Dict[str, Any]:
    try:
        done = await set_lead.set_lead(roles_port.session_ctx(ctx), args["list"], args["session"], as_agent=bool(args.get("agent")),
                                       seat_only=bool(args.get("seat_only")))
    except set_lead.LeadRefused as exc:
        raise ToolError(str(exc)) from exc
    except roles_service.RolesUnmeasured as exc:
        raise ToolError(f"could not read the sessions: {exc}") from exc
    roles_port.announce(ctx)
    return tool_result(done)


TOOLS: Dict[str, ToolSpec] = {
    "task_manager_leads_list": ToolSpec(
        "Read only: what the lead retrofit would do, per project (promote its current lead session, or your pick, into the Swarm project agent; "
        "promote_company for an HQ project: it becomes the company agent; pinned_seat when you pinned the seat; skipped, already_agent, no_lead or bad_pick otherwise; clear_seat empties an archived project's seat). Run it with task_manager_leads_update.",
        {"skip": _SKIP, "picks": _PICKS}, [], huddle_leads_list, "read"),
    "task_manager_leads_update": ToolSpec(
        "Promote each project's current lead session (or your pick) into its Swarm project agent, keeping its conversation: a running session is "
        "stopped and resumed. It waits for the owner's approval every time, Beast Mode included. Read task_manager_leads_list first.",
        {"skip": _SKIP, "picks": _PICKS}, [], huddle_leads_update, "inbox", prepare=_retrofit_prepare),
    "task_manager_lead_set": ToolSpec(
        "Set a project's lead (owner approves each time, Beast Mode included). Default: a project's Swarm project agent is re-pointed to the session; agent true "
        "promotes one where there is none (company agent on an HQ project). seat_only true pins only the Task Manager seat to a live or asleep "
        "session, agent untouched. session null empties an agentless seat, or with seat_only unpins.",
        {"list": {"type": "string", "description": "The project's id."}, "session": {"type": ["string", "null"], "description": "The session's stable key."},
         "agent": {"type": "boolean", "description": "Also make it the project agent (default false)."},
         "seat_only": {"type": "boolean", "description": "Pin the Task Manager seat only; never touch the Swarm agent (default false)."}},
        ["list", "session"], huddle_lead_set, "inbox", prepare=_lead_prepare, dedupe_by=("list",)),
}
