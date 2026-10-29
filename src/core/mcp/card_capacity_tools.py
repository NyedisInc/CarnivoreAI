
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Tuple

from src.core.mcp import card_tools, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.swarm import body
from src.core.swarm.cards import capacity, ops, port as card_port
from src.cplugs.sdk.cards import CardRefused

_SCOPE_PATTERN = r"^(company|project):[1-9][0-9]{0,9}$"


async def swarm_card_capacity(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def work() -> Any:
        await card_tools._caller(manager, caller)
        reading = await body.run_db(capacity.reading)
        return {"capacity": reading.as_dict(), "grants": (await card_port.get().policy_read("grants", {}))["grants"]}

    return await card_tools._guard(work())


async def _grant_checked(view: Any, caller: AgentCaller, args: dict) -> Tuple[Dict[str, Any], str, Any, str]:
    agent = await card_tools._caller(view, caller)
    scope = card_tools._text(args, "scope", required=True, limit=40)
    if "slots" not in args:
        raise ToolError("slots is required: a whole number from 0 to 20, or null to remove the grant")
    reason = card_tools._text(args, "reason", required=True, limit=500)
    kind, _, raw = scope.partition(":")
    scope_company = int(raw) if kind == "company" and raw.isdigit() else (
        await body.run_db(lambda c: capacity.company_of(c, int(raw))) if kind == "project" and raw.isdigit() else None)
    refused = capacity.grant_refusal(agent, scope, scope_company)
    if refused:
        raise CardRefused("not_allowed", refused)
    ops._no_secrets("grant reason", reason)
    return agent, scope, args["slots"], reason


async def _pace_checked(view: Any, caller: AgentCaller, args: dict) -> Tuple[Dict[str, Any], int, str]:
    agent = await card_tools._caller(view, caller)
    project_id = card_tools._int(args, "project_id", required=True)
    pace = args.get("pace")
    if pace not in ("normal", "asap"):
        raise ToolError("pace must be normal or asap")
    company = await body.run_db(lambda c: capacity.company_of(c, project_id))
    refused = capacity.pace_refusal(agent, project_id, company)
    if refused:
        raise CardRefused("not_allowed", refused)
    return agent, project_id, pace


async def _park(manager: Any, caller: AgentCaller, tool: str, summary: str, shown: dict,
                write: Callable[[Any], Awaitable[Dict[str, Any]]]) -> dict:
    async def go(_approved: bool) -> dict:
        return await card_tools._guard(write(manager.fresh()))

    return await write_tools.park(manager, caller, caller.current_session_id, caller.tmux_name, tool, summary, shown, go)


async def swarm_card_grant(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _agent, scope, slots, reason = await card_tools._guard(_grant_checked(manager, caller, args), wrap=False)

    async def write(view: Any) -> Dict[str, Any]:
        agent, scope_now, slots_now, reason_now = await _grant_checked(view, caller, args)
        done = await card_port.get().policy("set_grant", {"scope": scope_now, "slots": slots_now, "reason": reason_now}, f"agent:{agent['id']}")
        return {"grant": done["data"]["grant"]}

    what = "remove the agent grant of" if slots is None else f"grant {slots} agent slots to"
    return await _park(manager, caller, "swarm_card_grant", f"{what} {scope}: {reason}",
                       {"scope": scope, "slots": slots, "reason": reason}, write)


async def swarm_card_pace(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _agent, project_id, pace = await card_tools._guard(_pace_checked(manager, caller, args), wrap=False)

    async def write(view: Any) -> Dict[str, Any]:
        agent, project_now, pace_now = await _pace_checked(view, caller, args)
        done = await card_port.get().policy("set_rules", {"list_key": str(project_now), "changes": {"pace": pace_now}}, f"agent:{agent['id']}")
        return {"rules": done["data"]["rules"]}

    return await _park(manager, caller, "swarm_card_pace", f"set project {project_id}'s pace to {pace}",
                       {"project_id": project_id, "pace": pace}, write)


WRITE_TOOLS: frozenset = frozenset({"swarm_card_grant", "swarm_card_pace"})

TOOLS: Dict[str, Any] = {
    "swarm_card_capacity": (
        "Read the Swarm's capacity: CPU busy and whether the CPU floor is on, the highest fresh usage window and its floor, live agent bodies against the hard caps, and every grant.",
        {}, [], swarm_card_capacity),
    "swarm_card_grant": (
        "Set how many agents a project may run (SysOp: also a company; a company agent: the projects of its own company). slots 0..20, null removes the grant. "
        "A full grant makes a deal wait for a slot; it never stops work already running.",
        {"scope": {"type": "string", "pattern": _SCOPE_PATTERN}, "slots": {"type": ["integer", "null"], "minimum": 0, "maximum": 20},
         "reason": {"type": "string", "minLength": 1, "maxLength": 500}},
        ["scope", "slots", "reason"], swarm_card_grant),
    "swarm_card_pace": (
        "Set a project's pace from the owner's words: normal (one card per free agent) or asap (use every free slot, split cards, spawn up to the grant).",
        {"project_id": {"type": "integer", "minimum": 1}, "pace": {"type": "string", "enum": ["normal", "asap"]}},
        ["project_id", "pace"], swarm_card_pace),
}
