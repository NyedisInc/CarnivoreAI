
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from contextlib import closing
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.core import session_notes_store
from src.core.cross_session_search import strip_ansi
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.cplugs.host import mcp as cplug_mcp
from src.core.mcp import (session_target, companion_shell_tools, dashboard_tools, description_tools, project_color_tools, color_tools, dialog_tools, notification_tools, preference_tools,
                          project_lifecycle_tools, project_replica_tools, session_control_tools, automation_tools, beast_mode, bookmark_tools, lineage_tools, timeline_tools, board_tools, byoai_tools, crosstalk_tools, federated, launch_profile_tools, notify_tools,
                          messaging_tools, card_capacity_tools, card_tools, card_validate_tools, company_tools, group_tools, swarm_tools, pin_tools, pipeline_tools, session_delete_tools, session_folder_move_tools, session_purge_tools, project_tools, project_pack_tools, catalog_tools, mod_tools, skill_tools, read_tools, swarm_order_tools, write_tools, computers_tools, pack_machines_tools, app_update_tools, pack_relay_tools, api_key_tools, pack_skills_tools, pack_placement_tools, pack_transport_tools, pack_span_tools, pack_migrate_tools, pack_move_tools, browser_open_tools, files_open_tools, ui_show_tools, row_look_tools, pack_send_tools, usage_tools, session_usage_tools, swarm_switch_tools, beast_tools, autonomy_tools, deepsearch_tools)
from src.core.mcp import agent_tool_switches, aliases, merged_tools, pane_only, read_only_hint, tool_switches
from src.core.mcp import lean_answers
from src.core.mcp.approvals import call_context
from src.core.mcp.caller import AgentCaller
from src.cplugs.sdk import old_names
from src.core.flow_data import mcp_events
from src.core.pack.span import proxy_client as span_proxy
from src.core.swarm import guard as swarm_guard
from src.core.mcp.common import (  # noqa: F401
    _TARGET_SCHEMA,
    ToolError,
    _all_infos,
    _fail,
    _local_infos,
    _ok,
    _resolve,
    _summary,
)
from src.core.session_group_membership_migrate import resolve_session_uuid
from src.core.stream_redactor import StreamRedactor, redact_whole

logger = structlog.get_logger()

MAX_OUTPUT_LINES = 500
REDACT_MARGIN_LINES = 200
DEFAULT_OUTPUT_LINES = 100
MAX_LIST_ROWS = 200

async def whoami(manager: Any, caller: AgentCaller, args: dict) -> dict:
    hidden = agent_tool_switches.hidden_families(caller)
    if caller.external:
        return _ok({"external_client": caller.token_name, "scope": caller.scope, "hidden_families": hidden})
    for info in await _local_infos(manager):
        if info.tmux_session == caller.tmux_name:
            return _ok({**_summary(info), "session_id_in_env": caller.session_id, "hidden_families": hidden})
    raise ToolError("your session is not in the live listing")


async def sessions_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    include_asleep = args.get("include_asleep", False)
    if not isinstance(include_asleep, bool):
        raise ToolError("include_asleep must be true or false")
    include_closed = args.get("include_closed", False)
    if not isinstance(include_closed, bool):
        raise ToolError("include_closed must be true or false")
    full = lean_answers.detail_flag(args)
    limit = args.get("limit", MAX_LIST_ROWS if full else lean_answers.SESSIONS_LEAN_ROWS)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_ROWS:
        raise ToolError(f"limit must be a whole number from 1 to {MAX_LIST_ROWS}")
    resolver = session_target.TargetResolver(manager)
    rows = [_summary(i) for i in await resolver.infos()]
    if include_asleep:
        rows += [session_target.asleep_summary(r) for r in await resolver.asleep_rows()]
    if include_closed:
        rows += [session_target.closed_summary(r) for r in await resolver.closed_rows()]
    answer = {"sessions": rows[:limit], "truncated": len(rows) > limit}
    if answer["truncated"] and not full:
        answer["total"] = len(rows)
    return _ok(answer)


async def session_status(manager: Any, caller: AgentCaller, args: dict) -> dict:
    target = await session_target.resolve_target(manager, args, reach=session_target.STORED, tool="session_status")
    if not target.live:
        return _ok(session_target.asleep_summary(target.row))
    info = target.info
    return _ok({
        **_summary(info),
        "status_source": info.status_source,
        "startup_gate": info.startup_gate,
        "subagents_state": info.subagents_state,
        "subagents_running": info.subagents_running,
        "background_open": info.background_open,
        "background_processes": (
            info.background_processes.model_dump() if info.background_processes else None
        ),
        "pty_pid": info.session.pty_pid,
        "last_activity": info.session.last_activity,
    })


def redact_text(text: str) -> str:
    return redact_whole(text)


def clean_output(raw: bytes, lines: int) -> str:
    text = strip_ansi(raw.decode("utf-8", errors="replace")).replace("\r", "")
    return "\n".join(redact_text(text).split("\n")[-lines:])


async def session_read_output(manager: Any, caller: AgentCaller, args: dict) -> dict:
    info = await session_target.live_info(manager, args, "session_read_output")
    lines = args.get("lines", DEFAULT_OUTPUT_LINES)
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
        raise ToolError("lines must be a positive integer")
    lines = min(lines, MAX_OUTPUT_LINES)
    if federated.is_remote(info):
        raw = await federated.read_screen(info)
        return _ok({"target": info.session.id, "lines": lines, "output": clean_output(raw, lines), "source": "screen"})

    def capture() -> str:
        raw = manager.capture_scrollback(
            lines=lines + REDACT_MARGIN_LINES, session_id=info.session.id
        )
        return clean_output(raw, lines)

    output = await asyncio.to_thread(capture)
    return _ok({"target": info.session.id, "lines": lines, "output": output})


async def projects_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import projects_service
    from src.config import settings
    from src.models import ProjectResponse

    include_archived = args.get("include_archived", False)
    if not isinstance(include_archived, bool):
        raise ToolError("include_archived must be true or false")
    full = lean_answers.detail_flag(args)

    def read() -> list:
        view = projects_service.current_view(settings, include_archived=include_archived)
        return projects_service.views_to_responses(view, ProjectResponse)

    rows = await asyncio.to_thread(read)
    projects = [
        {"id": p.id, "name": p.name, "path": p.path, "description": p.description,
         "company_id": p.company_id, "company_name": p.company_name, "color": p.color, "archived_at": p.archived_at,
         "parent_project_id": p.parent_project_id, "storage": p.storage}
        for p in rows
    ]
    return _ok({"projects": projects if full else lean_answers.project_rows(projects)})


async def companies_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.config import settings
    from src.core.companies import store

    def read() -> list:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            return store.list_companies(conn)

    return _ok({"companies": await asyncio.to_thread(read)})


def _read_note(tmux_name: str) -> Optional[Any]:
    from src.config import settings

    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        uuid = resolve_session_uuid(conn, tmux_name)
        return None if uuid is None else session_notes_store.read_note(conn, uuid)


async def session_notes_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    target = await session_target.resolve_target(manager, args, reach=session_target.STORED, tool="session_notes_get")
    info = target.info
    if info is not None and federated.is_remote(info):
        answer = await federated.forward(info, "GET", "/sessions/{session_name}/note")
        return _ok({"revision": answer.get("revision"), "body": redact_text(str(answer.get("body", ""))),
                    "updated_at": answer.get("updated_at")})
    tmux_name = info.tmux_session if info is not None else target.tmux_name
    if not tmux_name:
        raise ToolError("that session has no tmux name, so it has no note")
    try:
        note = await asyncio.to_thread(_read_note, tmux_name)
    except (DatastoreUnreadableError, session_notes_store.SessionNotesUnavailable, OSError) as exc:
        raise ToolError(f"notes are unavailable: {exc}") from exc
    if note is None:
        raise ToolError("no stored session row for that target")
    return _ok({"revision": note.revision, "body": redact_text(note.body), "updated_at": note.updated_at})


Handler = Callable[[Any, AgentCaller, dict], Awaitable[dict]]

_TOOLS: dict[str, tuple[str, dict, list, Handler]] = {
    "whoami": ("Say who you are: your own session row (an external client gets its token name and scope) plus hidden_families, the tool families this computer is not offering you and how the owner turns each on. Call it when a tool you expect is missing.", {}, [], whoami),
    "sessions_list": ("Every live session on this computer and on each paired computer (host column). With include_asleep, "
                      "also this computer's asleep sessions, marked asleep: true (id is the session_uuid; wake with session_wake). "
                      "Shows 50 rows (total says how many exist); limit up to 200, or detail true for 200.",
                      {"include_asleep": {"type": "boolean", "description": "also list asleep sessions (default false)"},
                       "include_closed": {"type": "boolean", "description": "also list closed sessions with a conversation, e.g. closed by a reboot, marked closed: true (default false); reopen with session_wake"},
                       "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST_ROWS},
                       "detail": {"type": "boolean", "description": "200 rows instead of the lean 50"}},
                      [], sessions_list),
    "session_status": ("Status detail for one session, live or asleep (an asleep one answers asleep: true).",
                       {"target": _TARGET_SCHEMA}, ["target"], session_status),
    "session_read_output": (
        "Tail of a session's terminal output (max 500 lines, ANSI stripped, secrets redacted).",
        {"target": _TARGET_SCHEMA, "lines": {"type": "integer", "minimum": 1, "maximum": MAX_OUTPUT_LINES}},
        ["target"], session_read_output,
    ),
    "projects_list": ("The Carnivore project list: id, name, path, company_id and company_name (null when orphaned), color, archived_at, storage (pack state) and parent_project_id. Descriptions are cut to 120 characters; detail true gives them whole. Archived ones only with include_archived.",
                      {"include_archived": {"type": "boolean", "description": "also list archived projects (default false)"},
                       "detail": {"type": "boolean", "description": "whole descriptions instead of the lean default"}},
                      [], projects_list),
    "companies_list": ("Every company A-Z with its id, name, project_count, hue (its Swarm color-family hue, null for the default), parent_id (the company it sits under, null at the top level) and hq_project_id. A project with no company is orphaned.",
                       {}, [], companies_list),
    "session_notes_get": ("Get a session's markdown note (secrets redacted), live or asleep, with its revision and update time. session_notes_put needs that revision to write.", {"target": _TARGET_SCHEMA}, ["target"], session_notes_get),
}


_TOOLS.update(read_tools.TOOLS)
_TOOLS.update(write_tools.TOOLS)
_TOOLS.update(write_tools.READ_TOOLS)
_TOOLS.update(pipeline_tools.TOOLS)
_TOOLS.update(project_tools.TOOLS)
_TOOLS.update(project_pack_tools.TOOLS)
_TOOLS.update(company_tools.TOOLS)
_TOOLS.update(catalog_tools.READ_TOOLS)
_TOOLS.update(mod_tools.READ_TOOLS)
_TOOLS.update(mod_tools.WRITE_TOOLS)
_TOOLS.update(skill_tools.READ_TOOLS)
_TOOLS.update(skill_tools.WRITE_TOOLS)
_TOOLS.update(pin_tools.READ_TOOLS)
_TOOLS.update(pin_tools.WRITE_TOOLS)
_TOOLS.update(swarm_order_tools.READ_TOOLS)
_TOOLS.update(swarm_order_tools.WRITE_TOOLS)
_TOOLS.update(session_delete_tools.WRITE_TOOLS)
_TOOLS.update(session_folder_move_tools.WRITE_TOOLS)
_TOOLS.update(session_purge_tools.WRITE_TOOLS)
_TOOLS.update(group_tools.READ_TOOLS)
_TOOLS.update(group_tools.WRITE_TOOLS)
_TOOLS.update(automation_tools.TOOLS)
_TOOLS.update(board_tools.READ_TOOLS)
_TOOLS.update(board_tools.WRITE_TOOLS)
_TOOLS.update(byoai_tools.READ_TOOLS)
_TOOLS.update(crosstalk_tools.READ_TOOLS)
_TOOLS.update(crosstalk_tools.WRITE_TOOLS)
_TOOLS.update(launch_profile_tools.READ_TOOLS)
_TOOLS.update(notify_tools.WRITE_TOOLS)
_TOOLS.update(bookmark_tools.READ_TOOLS)
_TOOLS.update(lineage_tools.READ_TOOLS)
_TOOLS.update(deepsearch_tools.READ_TOOLS)
_TOOLS.update(timeline_tools.READ_TOOLS)
_TOOLS.update(bookmark_tools.WRITE_TOOLS)
_TOOLS.update(swarm_tools.TOOLS)
_TOOLS.update(card_tools.TOOLS)
_TOOLS.update(card_validate_tools.TOOLS)
_TOOLS.update(card_capacity_tools.TOOLS)
_ROUTE_MODULES = (session_control_tools, companion_shell_tools, dialog_tools, dashboard_tools, preference_tools, notification_tools,
                  project_lifecycle_tools, project_replica_tools, messaging_tools, description_tools, project_color_tools, color_tools, computers_tools, pack_machines_tools, app_update_tools, pack_relay_tools, api_key_tools, pack_skills_tools, pack_placement_tools, pack_transport_tools, pack_span_tools, pack_migrate_tools, pack_move_tools, browser_open_tools, files_open_tools, ui_show_tools, row_look_tools, pack_send_tools, usage_tools, session_usage_tools, swarm_switch_tools, beast_tools, autonomy_tools)
for _module in _ROUTE_MODULES:
    _TOOLS.update(_module.READ_TOOLS)
    _TOOLS.update(_module.WRITE_TOOLS)
ROUTE_GATES = {s.name: s.gate for m in _ROUTE_MODULES for s in getattr(m, "SPECS", ())}
_TOOLS.update(cplug_mcp.TOOLS)
for _old, _merge in merged_tools.MERGED.items():
    _TOOLS[_old] = (_merge.note, *_TOOLS[_merge.into][1:])


WRITE_TOOLS = frozenset(write_tools.TOOLS) | frozenset(pipeline_tools.TOOLS) | frozenset(project_tools.TOOLS) | frozenset(project_pack_tools.TOOLS) | frozenset(mod_tools.WRITE_TOOLS) | frozenset(skill_tools.WRITE_TOOLS) | frozenset(company_tools.TOOLS) | frozenset(pin_tools.WRITE_TOOLS) | frozenset(group_tools.WRITE_TOOLS) | frozenset(swarm_order_tools.WRITE_TOOLS) | frozenset(session_delete_tools.WRITE_TOOLS) | frozenset(session_folder_move_tools.WRITE_TOOLS) | frozenset(session_purge_tools.WRITE_TOOLS) | automation_tools.WRITE_TOOLS | frozenset(board_tools.WRITE_TOOLS) | frozenset(crosstalk_tools.WRITE_TOOLS) | frozenset(notify_tools.WRITE_TOOLS) | frozenset(bookmark_tools.WRITE_TOOLS) | swarm_tools.WRITE_TOOLS | card_tools.WRITE_TOOLS | card_validate_tools.WRITE_TOOLS | card_capacity_tools.WRITE_TOOLS | cplug_mcp.WRITE_TOOLS | frozenset().union(*(m.WRITE_TOOLS for m in _ROUTE_MODULES))
BEAST_SCOPE_TOOLS = WRITE_TOOLS - cplug_mcp.INBOX_TOOLS
_UNGATED_WRITES = frozenset({
    "session_notes_put",
    "notify",
}) | frozenset(pin_tools.WRITE_TOOLS) | frozenset(group_tools.WRITE_TOOLS) | frozenset(swarm_order_tools.WRITE_TOOLS) | cplug_mcp.UNGATED_WRITES | bookmark_tools.UNGATED_WRITES | frozenset().union(*(m.UNGATED_WRITES for m in _ROUTE_MODULES))
# external token
DIRECT_WRITES = frozenset({"swarm_switch_off", "autonomy_off", "beastmode_off"})


def is_write(name: str, live: Optional[dict] = None) -> bool:
    if name in WRITE_TOOLS:
        return True
    if cplug_mcp.SIDECAR_SEP not in name:
        return False
    tool = (cplug_mcp.live_tools() if live is None else live).get(name)
    return tool is not None and tool.gate != "read"


def allowed(caller: Optional[AgentCaller], name: str, switches: Optional[agent_tool_switches.AgentToolSwitches] = None,
            live: Optional[dict] = None, enabled_memo: Optional[dict] = None) -> bool:
    if not cplug_mcp.available(name, live, enabled_memo) or notify_tools.hidden_reason(caller, name) or tool_switches.hidden_reason(caller, name) or agent_tool_switches.hidden_reason(caller, name, switches):
        return False
    return not (caller is not None and caller.scope == "read" and is_write(name, live))


LARGE_BODY_TOOLS = cplug_mcp.BODY_LIMITS


GATED_TOOLS = call_context.GATED_TOOLS | cplug_mcp.INBOX_TOOLS


def tool_definitions(caller: Optional[AgentCaller] = None) -> list[dict]:
    switches = agent_tool_switches.current() if caller is not None else None
    live = cplug_mcp.live_tools()
    memo: dict[str, bool] = {}
    return [
        {
            "name": name,
            "description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": required},
            **({"annotations": hint} if (hint := read_only_hint.annotations(aliases.canonical(name), WRITE_TOOLS)) else {}),
        }
        for name, (desc, props, required, _h) in _TOOLS.items()
        if allowed(caller, name, switches, enabled_memo=memo)
    ] + [
        {
            "name": name,
            "description": tool.row[0],
            "inputSchema": {"type": "object", "properties": tool.row[1], "required": tool.row[2]},
            **({} if tool.gate != "read" else {"annotations": read_only_hint.READ_ONLY}),
        }
        for name, tool in live.items()
        if allowed(caller, name, switches, live, memo)
    ]


def tool_names() -> list[str]:
    return [*_TOOLS, *cplug_mcp.live_tools()]


def has_tool(name: Any) -> bool:
    return isinstance(name, str) and (name in _TOOLS or (cplug_mcp.SIDECAR_SEP in name and name in cplug_mcp.live_tools()))


def result_chars(result: Any) -> int:
    blocks = result.get("content") if isinstance(result, dict) else None
    return sum(len(b.get("text") or "") for b in blocks if isinstance(b, dict)) if isinstance(blocks, list) else 0


async def call_tool(manager: Any, caller: AgentCaller, name: str, args: Any) -> dict:
    event = mcp_events.begin(caller, name, args)
    called, name = name, aliases.canonical(name)
    args = merged_tools.with_preset(called, args) if called in merged_tools.MERGED else args
    mcp_events.take_gate_denied()
    if (why := tool_switches.hidden_reason(caller, name, called_as=called) or agent_tool_switches.hidden_reason(caller, called)):
        mcp_events.mark_gate_denied()
        result = _fail(why)
    else:
        result = await span_proxy.maybe_forward(manager, caller, name, args)
    if result is None:
        result = await _run_tool(manager, caller, name, args)
    mcp_events.finish(event, result, denied_by_gate=mcp_events.take_gate_denied())
    logger.info("mcp.tool_result", tool=called, chars=result_chars(result), is_error=bool(isinstance(result, dict) and result.get("isError")))
    return result


async def _run_tool(manager: Any, caller: AgentCaller, name: str, args: Any) -> dict:
    args = call_context.strip_legacy_arg(name, args if isinstance(args, dict) else {}, GATED_TOOLS)
    with call_context.calling(name, args), old_names.using(_old_name_via(caller), caller.tmux_name):
        return await _dispatch(manager, caller, name, args)


def _old_name_via(caller: AgentCaller) -> str:
    if caller.proxied_agent_id:
        return old_names.PEER
    return old_names.EXTERNAL if caller.from_token else old_names.PANE


async def _dispatch(manager: Any, caller: AgentCaller, name: str, args: dict) -> dict:
    live = cplug_mcp.live_tools() if cplug_mcp.SIDECAR_SEP in name else {}
    if not cplug_mcp.available(name, live):
        mcp_events.mark_gate_denied()
        return _fail(f"{name} is off: its plugin is disabled (plugins_list)")
    if (why := notify_tools.hidden_reason(caller, name)):
        mcp_events.mark_gate_denied()
        return _fail(why)
    if not allowed(caller, name, live=live):
        mcp_events.mark_gate_denied()
        return _fail(f"{name} changes things and this token is read-only; ask the owner for a write token")
    if (why := await swarm_guard.refusal(caller, name)):
        mcp_events.mark_gate_denied()
        return _fail(why)
    if (why := pane_only_refusal(caller, name, args)):
        mcp_events.mark_gate_denied()
        return _fail(why)
    if (why := await pane_only.refusal(manager, caller, name)):
        mcp_events.mark_gate_denied()
        return _fail(why)
    if caller.external and name in _UNGATED_WRITES and not beast_mode.approval_skip(name):
        return await _park_external(manager, caller, name, args if isinstance(args, dict) else {})
    handler = live[name].row[3] if name in live else _TOOLS[name][3]
    try:
        if caller.external and beast_mode.approval_skip(name) and name in _UNGATED_WRITES:
            return await beast_mode.run_unprompted(caller, name,
                lambda: handler(manager, caller, args if isinstance(args, dict) else {}), args=args if isinstance(args, dict) else {})
        return await handler(manager, caller, args if isinstance(args, dict) else {})
    except ToolError as exc:
        return _fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_tool_failed", tool=name, error=str(exc))
        return _fail(f"{name} failed: {type(exc).__name__}")


def pane_only_refusal(caller: AgentCaller, name: str, args: dict) -> Optional[str]:
    named = sorted(cplug_mcp.PANE_ONLY_ARGS.get(name, frozenset()) & set(args))
    if not named or not caller.from_token:
        return None
    return (f"{', '.join(named)} names a file on this computer, so only a session running here may pass it; "
            "send the file's content instead")


_TARGETED_WRITES = frozenset({"session_notes_put", "session_send_message", "session_pin", "session_unpin"}) | frozenset(
    s.name for m in (session_control_tools,) for s in m.SPECS if s.reach and s.gate == "arrange")


async def _park_external(manager: Any, caller: AgentCaller, name: str, args: dict) -> dict:
    inner = dataclasses.replace(caller, token_name="")
    key = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
    target_id = target_tmux = ""
    epoch: Optional[int] = None
    summary = name
    stored_uuid = ""
    if name in _TARGETED_WRITES:
        try:
            found = await session_target.resolve_target(manager, args, reach=session_target.PINNED, tool=name)
        except ToolError as exc:
            return _fail(str(exc))
        if found.live:
            info = found.info
            target_id, target_tmux, epoch = info.session.id, info.tmux_session or "", info.session.tmux_created_epoch
            summary = f"{name} on {info.host_label + ': ' if federated.is_remote(info) else ''}{target_tmux or target_id}"
        else:
            stored_uuid, target_tmux = found.session_uuid or "", found.tmux_name or ""
            summary = f"{name} on {found.kind.replace('_', ' ')} {target_tmux or stored_uuid}"

    async def run(approved: bool) -> dict:
        if stored_uuid:
            return await call_tool(manager.fresh(), inner, name, {**args, "target": stored_uuid})
        if not target_id:
            return await call_tool(manager, inner, name, args)
        fresh = manager.fresh()
        again = next((i for i in await _all_infos(fresh) if i.session.id == target_id), None)
        if again is None:
            return _fail("the target session no longer exists; nothing was done")
        if again.session.tmux_created_epoch != epoch:
            return _fail("the target is now a different pane than the one the owner approved; nothing was done")
        return await call_tool(fresh, inner, name, {**args, "target": target_id})

    try:
        return await write_tools.park(manager, caller, target_id or stored_uuid, target_tmux, name, summary, args, run, key)
    except ToolError as exc:
        return _fail(str(exc))
