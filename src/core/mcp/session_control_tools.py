"""
Each tool is a :class:`route_adapters.RouteTool` over the route the UI already calls, and resolves ``target`` through
the shared resolver (``session_target``), so an asleep session is reachable wherever the route accepts one:

- ``session_rename``: ``PATCH /sessions/{id}/name`` (the label; the tmux name never moves). ARRANGE.
- ``session_theme_set``: ``PATCH /sessions/{name}/theme`` (pin or clear a session's theme). ARRANGE.
- ``session_unread_set``: ``PATCH /sessions/{name}/unread`` (mark for follow-up or read). ARRANGE.
- ``session_notifications_set``: ``PATCH /sessions/records/{uuid}/notifications`` (mute one session). ARRANGE.
- ``session_wake``: ``POST /sessions/{uuid}/wake`` (resume an asleep session), or, for a CLOSED row with a known
  conversation (a reboot's ``tmux_missing``, #1980) named by its ``session_uuid``, ``POST /sessions/recreate``, the
  UI's reopen. ACT: waits unless Beast Mode is armed.
- ``session_mcp_reconnect``: ``POST /sessions/{id}/mcp/reconnect`` (type ``/mcp reconnect`` into an idle claude whose
  MCP servers dropped). ACT: waits unless Beast Mode is armed; refuses a busy session and writes nothing.
- ``session_interrupt``: ``POST /sessions/{id}/interrupt`` (one Escape). The ``session_send_keys`` gate: your own
  session runs at once, another waits (``mcp.gate_cross_session_actions``) unless Beast Mode is armed.
"""

from __future__ import annotations

from typing import Any

from src.core.mcp import federated, restart_account_args, route_adapters as ra, session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _ok


def _rename(call: ra.Call) -> Any:
    from src.models.session_requests import RenameSessionRequest

    t = call.target
    ident = call.session_id if t is None or t.live else t.session_uuid
    return call.route(call.request, ident, RenameSessionRequest(new_name=call.args["name"]))


def _theme(call: ra.Call) -> Any:
    from src.models.themes import UpdateThemeRequest

    return call.route(call.request, call.tmux_name, UpdateThemeRequest(theme_id=call.args.get("theme_id") or None))


def _unread(call: ra.Call) -> Any:
    from src.models.session_requests import SetUnreadRequest

    return call.route(call.request, call.tmux_name, SetUnreadRequest(unread=call.args["unread"]))


def _mute(call: ra.Call) -> Any:
    from src.models.notifications import MuteNotificationsRequest

    return call.route(call.request, call.session_uuid, MuteNotificationsRequest(muted=call.args["muted"]))


def _wake(call: ra.Call) -> Any:
    from src.api.session_sleep_routes import WakeRequest

    if call.target is not None and call.target.live:
        raise ToolError("that session is already live; nothing to wake")
    agent_type = call.args.get("agent_type")
    if call.target is not None and call.target.kind == session_target.KIND_CLOSED:
        return _reopen_closed(call, agent_type, *restart_account_args.read(call.args))
    account, pin = restart_account_args.read(call.args)
    start_fresh = call.args.get("start_fresh") is True
    if not (agent_type or account or start_fresh):
        return call.route(call.request, call.session_uuid, None)
    return call.route(call.request, call.session_uuid,
                      WakeRequest(agent_type=agent_type, account_id=account, account_pinned=pin, start_fresh=start_fresh))


def _reopen_closed(call: ra.Call, agent_type: Any, account: Any = None, pin: bool = False) -> Any:
    import importlib

    recreate_routes = importlib.import_module("src.api.recreate_routes")
    chosen = agent_type or (call.target.row or {}).get("agent_type")
    if not chosen:
        raise ToolError("that closed session has no recorded agent_type: pass agent_type (a wrapper id)")
    return recreate_routes.recreate_session(
        call.request, recreate_routes.RecreateRequest(
            session_uuid=call.session_uuid, agent_type=chosen, account_id=account, account_pinned=pin))


def _wake_summary(args: dict, target: Any) -> str:
    on = restart_account_args.shown(args.get("account"), bool(args.get("always_use_account")))
    if target is not None and target.kind == session_target.KIND_CLOSED:
        return f"reopen the closed session {target.shown} (resumes its conversation{on})"
    what = "starts a new conversation" if args.get("start_fresh") is True else "resumes its conversation"
    return f"wake the asleep session {target.shown if target else args.get('target')} ({what}{on})"


async def _wake_precheck(args: dict, target: Any) -> None:
    account, pin = restart_account_args.read(args)
    if target is not None and not target.live:
        agent = args.get("agent_type") or (target.row or {}).get("agent_type")
        await restart_account_args.refuse_bad(account, pin, agent)


def _mcp_reconnect(call: ra.Call) -> Any:
    from src.api.mcp_reconnect_routes import McpReconnectRequest

    return call.route(call.request, call.session_id, McpReconnectRequest(server=call.args.get("server")))


def _mcp_reconnect_summary(args: dict, target: Any) -> str:
    which = args.get("server") or "every dropped server"
    return f"type /mcp reconnect into {target.shown if target else args.get('target')} ({which}); refused if it is busy"


SPECS = (
    ra.RouteTool(
        name="session_rename", route="src.api.session_rename_routes:rename_session_endpoint", gate=ra.ARRANGE,
        description="Set a session's label, live or asleep (what the drawer shows; the tmux name never moves). Up to 200 characters.",
        properties={"name": {"type": "string", "maxLength": 200}}, required=("name",),
        reach=session_target.STORED, local_only=False, invoke=_rename, example={"name": "build bot"},
    ),
    ra.RouteTool(
        name="session_theme_set", route="src.api.session_theme_routes:set_session_theme", gate=ra.ARRANGE,
        description="Pin a theme on one session (theme_id from themes_list), or clear it (theme_id null) so it follows "
                    "its project's and then the global theme.",
        properties={"theme_id": {"type": ["string", "null"]}}, required=("theme_id",),
        reach=session_target.STORED, invoke=_theme, example={"theme_id": "matrix"},
    ),
    ra.RouteTool(
        name="session_unread_set", route="src.api.session_theme_routes:set_session_unread", gate=ra.ARRANGE,
        description="Mark one session unread for follow-up (unread true), or read (false), on every device.",
        properties={"unread": {"type": "boolean"}}, required=("unread",),
        reach=session_target.STORED, invoke=_unread, example={"unread": True},
    ),
    ra.RouteTool(
        name="session_notifications_set", route="src.api.session_records_routes:set_session_notification_policy",
        gate=ra.ARRANGE,
        description="Mute (muted true) or unmute one session's notifications, live or asleep. A state, not a toggle.",
        properties={"muted": {"type": "boolean"}}, required=("muted",),
        reach=session_target.STORED, needs_uuid=True, invoke=_mute, example={"muted": True},
    ),
    ra.RouteTool(
        name="session_mcp_reconnect", route="src.api.mcp_reconnect_routes:reconnect_mcp", gate=ra.ACT,
        description="Reconnect the MCP servers a live claude lost (listing mcp_health.dropped): types /mcp reconnect. "
                    "Idle sessions only; busy is refused. Waits for the owner's approval unless Beast Mode is armed.",
        properties={"server": {"type": "string", "maxLength": 200}}, reach=session_target.LIVE,
        invoke=_mcp_reconnect, summary=_mcp_reconnect_summary, example={},
    ),
    ra.RouteTool(
        name="session_wake", route="src.api.session_sleep_routes:wake_session", gate=ra.ACT,
        description="Wake an asleep session (target its session_uuid or tmux name from sessions_list include_asleep) onto the same "
                    "conversation; a CLOSED one (include_closed) with a known conversation reopens by session_uuid. "
                    "agent_type picks a launch wrapper. start_fresh starts a new conversation on the same row when the stored one never wrote a transcript. account (with always_use_account) resumes on that claude account. "
                    "Waits for the owner's approval unless Beast Mode is armed.",
        properties={"agent_type": {"type": "string"},
                    "start_fresh": {"type": "boolean", "description": "Start a new conversation on the same row when the stored "
                                    "conversation never wrote a transcript; otherwise the wake resumes as normal (default false)."},
                    **restart_account_args.PROPERTIES},
        reach=session_target.CLOSED, needs_uuid=True,
        invoke=_wake, summary=_wake_summary, precheck=_wake_precheck, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)


async def session_interrupt(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_interrupt_routes
    from src.core.mcp.write_tools import _gated, _via_route
    from src.models.background_work import InterruptRequest

    if set(args) - {"target"}:
        raise ToolError("session_interrupt takes only target")
    info = await session_target.live_info(manager, args, "session_interrupt")
    request = ra.route_request(manager)

    async def run(_approved: bool) -> dict:
        if federated.is_remote(info):
            return _ok(await federated.forward(info, "POST", "/sessions/{session_id}/interrupt", {"confirm": True}))
        answer = await _via_route(session_interrupt_routes.interrupt_session(request, info.session.id,
                                                                             InterruptRequest(confirm=True)))
        return _ok(answer.model_dump())

    return await _gated(manager, caller, info, "session_interrupt", "press Escape once (interrupt the agent)", {}, run)


WRITE_TOOLS["session_interrupt"] = (
    "Interrupt a live agent session: press Escape once. Aimed at another session, or any session on a paired "
    "computer, it waits for the owner's approval unless Beast Mode is armed.",
    {"target": _TARGET_SCHEMA}, ["target"], session_interrupt,
)
