
from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder

from src.core.mcp import route_adapters as ra, session_target
from src.core.mcp.common import ToolError
from src.core.session_git.diff import MAX_PATH_CHARS as MAX_DIFF_PATH_CHARS
from src.core.skill_fires.tally import DEFAULT_RECENT_FIRES as DEFAULT_SKILL_FIRES, MAX_RECENT_FIRES as MAX_RECENT

DEFAULT_ROWS = 20
MAX_ROWS = 100


def _limit(args: dict, default: int, maximum: int) -> int:
    limit = args.get("limit", default)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ToolError(f"limit must be a whole number from 1 to {maximum}")
    return limit


DEFAULT_SUBAGENT_ROWS = 50
MAX_SUBAGENT_ROWS = 200

_LIMIT_SCHEMA = {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}


def _read(**fields: Any) -> ra.RouteTool:
    return ra.RouteTool(gate=ra.READ, redact=True, **fields)


def _per_session(name: str, route: str, description: str, **extra: Any) -> ra.RouteTool:
    extra.setdefault("invoke", lambda call: call.route(call.request, call.session_id))
    return _read(name=name, route=route, description=description, reach=session_target.LIVE, **extra)


async def _git_diff(call: ra.Call) -> Any:
    path = call.args.get("path")
    if path is None:
        if "staged" in call.args:
            raise ToolError("staged only applies to one file's diff: give a path, or leave both out for the changed-file list")
        from src.api.session_git_routes import get_session_git_status

        return await get_session_git_status(call.request, call.session_id)
    if not isinstance(path, str) or not 1 <= len(path) <= MAX_DIFF_PATH_CHARS:
        raise ToolError(f"path must be a string of 1 to {MAX_DIFF_PATH_CHARS} characters")
    return await call.route(call.request, call.session_id, path=path, staged=call.args.get("staged") is True)


async def _prompts(call: ra.Call) -> dict:
    limit = _limit(call.args, DEFAULT_ROWS, MAX_ROWS)
    prompts = jsonable_encoder(await call.route(call.request, call.session_id)).get("prompts", [])
    return {"prompts": prompts[-limit:], "total": len(prompts)}


async def _conversations(call: ra.Call) -> Any:
    limit = _limit(call.args, DEFAULT_ROWS, MAX_ROWS)
    answer = jsonable_encoder(await call.route(call.session_uuid))
    return {**answer, "previous": answer.get("previous", [])[:limit]}


async def _subagents(call: ra.Call) -> Any:
    limit = _limit(call.args, DEFAULT_SUBAGENT_ROWS, MAX_SUBAGENT_ROWS)
    answer = jsonable_encoder(await call.route(call.request, call.session_id))
    rows = answer.get("subagents", [])
    ordered = [r for r in rows if r.get("status") == "running"] + [r for r in rows if r.get("status") != "running"]
    return {**answer, "subagents": ordered[:limit], "returned": min(limit, len(ordered)), "truncated": len(ordered) > limit}


def _background_agents(call: ra.Call) -> Any:
    cwd = call.args.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ToolError("cwd must be a string")
    return call.route(call.request, cwd=cwd)


def _skill_fires(call: ra.Call) -> Any:
    limit = _limit(call.args, DEFAULT_SKILL_FIRES, MAX_RECENT)
    return call.route(call.request, call.session_id, limit=limit)


SPECS = (
    _per_session(
        "session_subagents_list", "src.api.subagent_routes:get_session_subagents",
        "Subagents a live agent started in its current conversation, running first then newest activity, with counts by state. limit: "
        "1 to 200, default 50 (counts cover all of them; returned and truncated say what was cut). Claude agents only; earlier conversations are not read.",
        properties={"limit": {"type": "integer", "minimum": 1, "maximum": MAX_SUBAGENT_ROWS}}, invoke=_subagents,
        example={"limit": 5},
    ),
    _per_session(
        "session_timers_list", "src.api.session_timers_routes:get_session_timers",
        "Timers (scheduled wakeups and loops) in a live agent's current conversation, with counts and the background work "
        "the watcher sees open.",
    ),
    _per_session(
        "session_background_jobs_list", "src.api.session_background_work_routes:get_session_background_work",
        "Tool shells a live Claude agent is running (pid, start, command, which subagent launched it), oldest first. "
        "Codex and plain shells answer not_applicable.",
    ),
    _per_session(
        "session_pane_facts_get", "src.api.session_pane_facts_routes:get_session_pane_facts",
        "Pane facts of a live agent now: working directory, foreground command, git branch and size. Every field is null "
        "when the pane cannot be read.",
    ),
    _per_session(
        "session_token_usage_get", "src.api.session_token_usage_routes:get_session_token_usage",
        "Token spend, cost estimate and context headroom (how full the context window is) of a live agent.",
    ),
    _per_session(
        "session_prompts_list", "src.api.session_prompt_texts_routes:get_prompt_texts",
        "The newest prompts typed into a live Claude agent, oldest first, from its transcript, with the total. limit: 1 to 100, "
        "default 20. Empty for a Codex or unreadable transcript.",
        properties={"limit": _LIMIT_SCHEMA}, invoke=_prompts, example={"limit": 3},
    ),
    _per_session(
        "session_tasks_list", "src.api.session_tasks_routes:get_session_tasks",
        "The task list a live Claude agent keeps (its TodoWrite or tasks). state is ok, empty, unknown, unsupported "
        "(not Claude) or remote. Takes the page's short push lease.",
    ),
    _read(
        name="session_skill_fires_list", route="src.api.session_skill_fires_routes:get_session_skill_fires",
        description="Newest skill fires (which skill ran, when) in a live agent's current conversation.",
        reach=session_target.LIVE,
        properties={"limit": {"type": "integer", "minimum": 1, "maximum": MAX_RECENT, "description": "Rows, default 20."}},
        invoke=_skill_fires, example={"limit": 5},
    ),
    _read(
        name="session_git_diff_get", route="src.api.session_git_routes:get_session_git_diff",
        description="One changed file's diff since HEAD in a live agent's repository (text capped at 256 KB; staged true: only "
                    "what is staged). Leave path out to get the changed-file list; path must be exactly as that list names it. "
                    "Takes the page's short push lease.",
        reach=session_target.LIVE,
        properties={"path": {"type": "string", "minLength": 1, "maxLength": MAX_DIFF_PATH_CHARS},
                    "staged": {"type": "boolean", "description": "Only the staged change. Default false."}},
        invoke=_git_diff, example={"path": "src/a.py"},
    ),
    _read(
        name="session_local_servers_list", route="src.api.session_logs_routes:get_local_servers",
        description="Dev servers (port and URL) the app detected in a live agent's output. Pure read; never probes. Empty when none "
                    "were seen.",
        reach=session_target.LIVE,
        invoke=lambda call: call.route(call.request, call.tmux_name),
    ),
    _read(
        name="session_conversations_list", route="src.api.session_conversations_routes:list_conversations",
        description="An agent's current conversation and the newest earlier ones (limit 1 to 100, default 20; previous_count "
                    "is the whole count), with summaries. Works for a live or asleep agent.",
        reach=session_target.STORED, needs_uuid=True, properties={"limit": _LIMIT_SCHEMA}, example={"limit": 2},
        invoke=_conversations,
    ),
    _read(
        name="session_resume_candidates_list", route="src.api.session_recent_routes:list_recent_sessions",
        description="Stopped agents on this computer that could be resumed, newest first. include_archived adds deleted records; "
                    "include_automated adds scheduler and headless runs.",
        properties={"include_archived": {"type": "boolean"}, "include_automated": {"type": "boolean"}},
        invoke=lambda call: call.route(
            call.request, include_archived=call.args.get("include_archived") is True,
            include_automated=call.args.get("include_automated") is True),
        example={"include_archived": True},
    ),
    _read(
        name="session_adoption_candidates_list", route="src.api.session_attach_routes:list_attachable_sessions",
        description="Tmux panes on Carnivore's socket that were started outside it and could be adopted, with whether Carnivore "
                    "created each. Refused when tmux cannot be read.",
        invoke=lambda call: call.route(call.request),
    ),
    _read(
        name="session_background_agents_list", route="src.api.session_discovery_routes:list_background_sessions",
        description="Claude background agents: forks that run with no terminal, so no tmux pane. Check measured, not an empty "
                    "answer. cwd limits it to agents started under a path.",
        properties={"cwd": {"type": "string", "description": "Only sessions started under this path."}},
        invoke=_background_agents,
        example={"cwd": "/tmp"},
    ),
    _read(
        name="session_attention_get", route="src.api.attention_routes:attention_diagnostics",
        description="How fresh the status watcher's reading of each agent is, and what decided its status. Reads memory; captures "
                    "no pane.",
        invoke=lambda call: call.route(call.request),
    ),
    _read(
        name="session_restore_offer_get", route="src.api.restore_offer_routes:get_restore_offer",
        description="The open reboot restore offer: agents that were running before the machine restarted and are still closed. "
                    "offer is null when none is open. Accepting stays the owner's click.",
        invoke=lambda call: call.route(),
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
