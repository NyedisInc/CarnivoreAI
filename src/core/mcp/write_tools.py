
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional

import structlog
from fastapi import HTTPException

from src.core.db import DatastoreUnreadableError
from src.core.mcp import beast_mode, federated, in_use as in_use_mod, pending, restart_account_args, session_target
from src.core.mcp.approvals import call_context, runtime as approval_runtime, wording
from src.core.mcp.caller import AgentCaller
from src.core.swarm import delivery as swarm_delivery
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _fail, _ok

logger = structlog.get_logger()

MAX_CREATED_PER_AGENT = 5
MAX_CREATED_TOTAL = 20
CREATE_ARGS = frozenset({"working_dir", "project", "agent_type", "launch_profile", "name", "peer", "account", "always_use_account"})
MAX_KEYS_TEXT = 1000
MAX_KEY_NAMES = 20
MAX_NOTE_CHARS = 100_000
MAX_MESSAGE_CHARS = 20_000

NAMED_KEYS = {
    "Enter": b"\r", "Escape": b"\x1b", "Tab": b"\t", "BSpace": b"\x7f",
    "Up": b"\x1b[A", "Down": b"\x1b[B", "Right": b"\x1b[C", "Left": b"\x1b[D",
    "C-c": b"\x03", "C-d": b"\x04",
}

_created: dict[str, tuple[str, float]] = {}
_create_lock = asyncio.Lock()
_reserved: list[str] = []


def gate_enabled() -> bool:
    from src.config import settings

    try:
        return bool(settings.load_auth_config().mcp.gate_cross_session_actions)
    except (ValueError, OSError) as exc:
        logger.warning("mcp_gate_config_unreadable", error=str(exc))
        return True


def _request(manager: Any) -> Any:
    app = getattr(manager, "app", None)
    if app is None:
        raise ToolError("write tools are unavailable on this transport")
    return SimpleNamespace(app=app)


def _detail(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        code, reason = detail.get("code"), detail.get("reason")
        detail = detail.get("message") or detail.get("detail") or (
            f"{code}: {reason}" if code and isinstance(reason, str) and reason else code) or detail
    return f"refused ({exc.status_code}): {str(detail)[:300]}"


async def _via_route(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc


def _text_arg(args: dict, key: str, limit: int) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} is required and must be non-empty text")
    if len(value) > limit:
        raise ToolError(f"{key} is over the {limit} character limit")
    return value


async def session_notes_put(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.session_notes_routes import UpdateSessionNoteRequest, put_session_note

    target = await session_target.resolve_target(manager, args, reach=session_target.STORED, tool="session_notes_put")
    if target.live and federated.is_remote(target.info):
        raise ToolError("session_notes_put is local only: a paired computer's notes are written there")
    tmux_name = target.info.tmux_session if target.live else target.tmux_name
    if not tmux_name:
        raise ToolError("that session has no tmux name, so it has no note")
    revision = args.get("expected_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ToolError("expected_revision is required: the revision session_notes_get returned (0 if none)")
    body = args.get("body")
    if not isinstance(body, str) or len(body) > MAX_NOTE_CHARS:
        raise ToolError(f"body is required text of at most {MAX_NOTE_CHARS} characters")
    result = await _via_route(put_session_note(
        _request(manager), tmux_name,
        UpdateSessionNoteRequest(body=body, expected_revision=revision),
    ))
    return _ok({"status": result.status, "revision": result.revision})


def _created_counts(live_ids: set[str], caller: AgentCaller, listed_at: float) -> tuple[int, int]:
    for sid, (_tmux, recorded) in list(_created.items()):
        if sid not in live_ids and recorded < listed_at:
            del _created[sid]
    mine = sum(1 for tmux, _t in _created.values() if tmux == caller.tmux_name) + _reserved.count(caller.tmux_name)
    return mine, len(_created) + len(_reserved)


async def session_create(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.session_crud_routes import create_session
    from src.models import CreateSessionRequest

    unknown = sorted(set(args) - CREATE_ARGS)
    if unknown:
        raise ToolError(f"unsupported arguments: {', '.join(unknown)}; allowed: {', '.join(sorted(CREATE_ARGS))}")
    fields: dict[str, Any] = {}
    for key in ("agent_type", "name"):
        if key in args:
            fields[key] = _text_arg(args, key, 200)
    picked = _launch_profile_pick(args, fields)
    account = _text_arg(args, "account", 200) if "account" in args else None
    pin_account = args.get("always_use_account", False)
    if not isinstance(pin_account, bool):
        raise ToolError("always_use_account must be true or false")
    if pin_account and account is None:
        raise ToolError("always_use_account needs account")
    if account is not None and "peer" in args:
        raise ToolError("an account is chosen on the computer that runs the session; a paired computer uses its own "
                        "active account, so leave account out with peer")
    working_dir = args.get("working_dir")
    project = args.get("project")
    if (working_dir is None) == (project is None):
        raise ToolError("give exactly one of working_dir or project")
    if "peer" in args:
        if picked is not None:
            raise ToolError("launch_profile picks a profile on this computer; a paired computer takes agent_type "
                            "(claude, codex or shell) and resolves it with its own launch profiles")
        if working_dir is None:
            raise ToolError("a create on a paired computer needs working_dir (a path on that computer), not project")
        return await _create_on_peer(manager, caller, _text_arg(args, "peer", 200), _text_arg(args, "working_dir", 4096), fields)
    if project is not None:
        working_dir = await _project_path(_text_arg(args, "project", 200))
    working_dir = os.path.realpath(os.path.expanduser(_text_arg({"w": working_dir}, "w", 4096)))
    if not os.path.isdir(working_dir):
        raise ToolError("working_dir is not an existing directory")
    request = CreateSessionRequest(
        working_dir=working_dir, agent_type=picked or fields.get("agent_type"), label=fields.get("name"),
        project_name=os.path.basename(working_dir), account_id=account, account_pinned=pin_account,
    )
    if account is not None:
        await _check_account(request)

    async def run(_approved: bool) -> dict:
        async with _create_lock:
            listed_at = time.monotonic()
            live = await manager.live_ids_now()
            mine, total = _created_counts(live, caller, listed_at)
            if mine >= MAX_CREATED_PER_AGENT:
                raise ToolError(f"you already have {mine} live sessions you created (limit {MAX_CREATED_PER_AGENT})")
            if total >= MAX_CREATED_TOTAL:
                raise ToolError(f"{total} agent-created sessions are live (limit {MAX_CREATED_TOTAL})")
            session = await _via_route(create_session(_request(manager), request))
            _created[session.id] = (caller.tmux_name, time.monotonic())
        logger.info("mcp_session_created", session_id=session.id, creator=caller.tmux_name, launch_profile=picked)
        return _ok({"id": session.id, "working_dir": session.working_dir, "launch": _launch_shown(request.agent_type)})

    summary = f"create a session in {working_dir}"
    shown = {"working_dir": working_dir, "agent_type": request.agent_type, "name": request.label}
    if account is not None:
        shown["account"] = account + (" (always)" if pin_account else "")
    if beast_mode.approval_skip("session_create"):
        return await beast_mode.run_unprompted(caller, "session_create", lambda: run(True),
                                                summary=summary, args=shown)
    return await park(manager, caller, "", "", "session_create", summary, shown, run)


async def _check_account(request: Any) -> None:
    await restart_account_args.refuse_bad(request.account_id, request.account_pinned, request.agent_type)


def _launch_profile_pick(args: dict, fields: dict) -> Optional[str]:
    if "launch_profile" not in args:
        return None
    picked = _text_arg(args, "launch_profile", 200)
    asked = fields.get("agent_type")
    if asked is not None and asked.lower() != picked.lower():
        raise ToolError(f"launch_profile {picked!r} and agent_type {asked!r} name different launches; give one of them")
    from src.config import settings
    from src.core.launch_profiles import create_seam
    from src.core.launch_profiles.resolve import LaunchProfileNotFound

    try:
        create_seam.check_explicit_pick(settings, picked)
    except LaunchProfileNotFound as exc:
        raise ToolError(f"no launch profile {picked!r}; see launch_profiles_list "
                        f"(available: {', '.join(getattr(exc, 'available', [])) or 'none'})") from None
    return picked


def _launch_shown(agent_type: Optional[str]) -> dict:
    from src.config import settings
    from src.core.launch_profiles.resolve import LaunchRequest, pick_profile
    from src.core.launch_profiles.summary import summary_row

    shown = summary_row(pick_profile(LaunchRequest(profiles=tuple(settings.get_launch_profiles()), agent_type=agent_type)))
    return {key: shown[key] for key in ("id", "label", "harness", "account", "model", "permissions_badge")}


async def _create_on_peer(manager: Any, caller: AgentCaller, peer_name: str, working_dir: str, fields: dict) -> dict:
    peer = await federated.find_peer(peer_name)
    body = {"working_dir": working_dir, **({"agent_type": fields["agent_type"]} if "agent_type" in fields else {}),
            **({"label": fields["name"]} if "name" in fields else {})}

    async def run(approved: bool) -> dict:
        async with _create_lock:
            listed_at = time.monotonic()
            live = await manager.live_ids_now()
            mine, total = _created_counts(live, caller, listed_at)
            if mine >= MAX_CREATED_PER_AGENT:
                raise ToolError(f"you already have {mine} live sessions you created (limit {MAX_CREATED_PER_AGENT})")
            if total >= MAX_CREATED_TOTAL:
                raise ToolError(f"{total} agent-created sessions are live (limit {MAX_CREATED_TOTAL})")
            _reserved.append(caller.tmux_name)
        created = None
        try:
            created = await federated.create(peer, body)
        finally:
            async with _create_lock:
                _reserved.remove(caller.tmux_name)
                if created is not None:
                    _created[created["id"]] = (caller.tmux_name, time.monotonic())
        logger.info("mcp_session_created", session_id=created["id"], creator=caller.tmux_name, peer=peer.key)
        return _ok({"id": created["id"], "working_dir": created.get("working_dir")})

    key = hashlib.sha256(json.dumps([peer.key, body], sort_keys=True).encode()).hexdigest()
    shown = {"peer": peer.label, "working_dir": working_dir, **{k: fields[k] for k in ("agent_type", "name") if k in fields}}
    extra = "".join(f", {k} {json.dumps(shown[k])}" for k in ("agent_type", "name") if k in shown)
    summary = f"create a session on {peer.label} in {json.dumps(working_dir)[1:-1]}{extra}"
    if beast_mode.approval_skip("session_create"):
        return await beast_mode.run_unprompted(caller, "session_create", lambda: run(True),
                                                summary=summary, args=shown)
    return await park(manager, caller, "", "", "session_create", summary, shown, run, key)


async def _project_path(name: str) -> str:
    from src.api import projects_service
    from src.config import settings
    from src.models import ProjectResponse

    def read() -> list:
        view = projects_service.current_view(settings)
        return projects_service.views_to_responses(view, ProjectResponse)

    for project in await asyncio.to_thread(read):
        if project.name.lower() == name.lower() or project.id == name:
            return project.path
    raise ToolError(f"no project named {name!r}; see projects_list")


async def session_send_message(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.crosstalk import bus
    info = await session_target.live_info(manager, args, "session_send_message")
    text = _text_arg(args, "text", MAX_MESSAGE_CHARS)
    result = await bus.send(manager, caller, to=info.session.id, text=text, action="session_send_message")
    return result if "content" in result else _ok(result)


def _keys_payload(args: dict) -> tuple[bytes, dict]:
    text = args.get("text", "")
    keys = args.get("keys", [])
    if not isinstance(text, str) or len(text) > MAX_KEYS_TEXT:
        raise ToolError(f"text must be a string of at most {MAX_KEYS_TEXT} characters")
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in text):
        raise ToolError("text may not contain control characters; press them by name in keys")
    if not isinstance(keys, list) or len(keys) > MAX_KEY_NAMES or not all(isinstance(k, str) for k in keys):
        raise ToolError(f"keys must be a list of at most {MAX_KEY_NAMES} names")
    bad = [k for k in keys if k not in NAMED_KEYS]
    if bad:
        raise ToolError(f"unknown keys {bad[:3]}; allowed: {', '.join(NAMED_KEYS)}")
    if not text and not keys:
        raise ToolError("give text, keys, or both")
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolError("text contains an unpaired surrogate and cannot be sent as UTF-8") from exc
    data = raw + b"".join(NAMED_KEYS[k] for k in keys)
    shown = {"text": json.dumps(text)[1:-1], "keys": list(keys)}
    return data, shown


async def _resolved_again(app: Any, target_id: str, epoch: Optional[int]) -> Any:
    for info in await app.state.session_manager.list_session_infos():
        if info.session.id == target_id and info.host_key == "local":
            if info.session.tmux_created_epoch != epoch:
                raise ToolError("the target is now a different pane than the one you asked about; nothing was done")
            return info
    raise ToolError("the target session no longer exists; nothing was done")


async def _pane_live(app: Any, info: Any) -> bool:
    from src.api.one_shot_routes import _read_pane_signals

    backend = app.state.services.registry.get_backend(info.session.id)
    if backend is None:
        return False
    _command, dead = await _read_pane_signals(backend, info.tmux_session)
    return dead != "1"


async def _own_dialog_open(app: Any, info: Any) -> bool:
    fresh = await app.state.session_manager.get_session_info(session_id=info.session.id)
    if fresh is None:
        return True
    return fresh.activity_status == "question" or fresh.startup_gate != "ready"


async def _do_send_keys(app: Any, target_id: str, epoch: Optional[int], data: bytes) -> dict:
    info = await _resolved_again(app, target_id, epoch)
    try:
        await asyncio.to_thread(swarm_delivery.record_for_session_row, info.session_row_id, "send_keys", f"send_keys:{target_id}")
    except (DatastoreUnreadableError, sqlite3.Error, OSError):
        raise ToolError("the Swarm could not record who sent this; nothing was done") from None
    await app.state.session_manager.send_input(data.decode("utf-8"), session_id=target_id)
    return _ok({"sent_bytes": len(data)})


async def _do_restart(app: Any, target_id: str, epoch: Optional[int], approved: bool, was_live: bool,
                      account: Optional[str] = None, pin: bool = False) -> dict:
    info = await _resolved_again(app, target_id, epoch)
    if not info.tmux_session:
        raise ToolError("that session has no tmux name to restart")
    confirmed = False
    if approved:
        if await _pane_live(app, info) != was_live:
            raise ToolError("the pane's state changed since the owner was asked; nothing was restarted")
        confirmed = was_live
    return _ok(await _via_route(app.state.session_manager.respawn_session(
        info.tmux_session, live_restart_confirmed=confirmed, account_id=account, account_pinned=pin)))


def _session_uuid_of_row(row_id: int) -> Optional[str]:
    from contextlib import closing

    from src.config import settings
    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        row = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (row_id,)).fetchone()
    return None if row is None else str(row[0])


async def _do_stop(app: Any, target_id: str, epoch: Optional[int]) -> dict:
    from src.api.session_sleep_routes import sleep_by_uuid

    info = await _resolved_again(app, target_id, epoch)
    if info.session_row_id is None:
        raise ToolError("no stored row for that session")
    session_uuid = await asyncio.to_thread(_session_uuid_of_row, info.session_row_id)
    if session_uuid is None:
        raise ToolError("no stored row for that session")
    result = await _via_route(sleep_by_uuid(app.state, session_uuid))
    return _ok({"status": result.status, "detail": result.detail})


async def _do_send_keys_remote(target_id: str, epoch: Optional[int], data: bytes) -> dict:
    info = await federated.resolved_again(target_id, epoch)
    await federated.send_input(info, data)
    return _ok({"sent_bytes": len(data)})


async def _do_restart_remote(target_id: str, epoch: Optional[int], approved: bool, was_live: bool) -> dict:
    info = await federated.resolved_again(target_id, epoch)
    confirmed = False
    if approved:
        if federated.pane_live(info) != was_live:
            raise ToolError("the pane's state changed since the owner was asked; nothing was restarted")
        confirmed = was_live
    return _ok(await federated.forward(info, "POST", "/sessions/respawn", {"confirm_restart_live": confirmed}))


async def _do_stop_remote(target_id: str, epoch: Optional[int]) -> dict:
    info = await federated.resolved_again(target_id, epoch)
    answer = await federated.forward(info, "POST", "/sessions/{session_uuid}/sleep")
    return _ok({"status": answer.get("status"), "detail": answer.get("detail")})


async def _as_result(call: Awaitable[dict]) -> dict:
    try:
        return await call
    except ToolError as exc:
        return _fail(str(exc))


async def _gated(
    manager: Any, caller: AgentCaller, info: Any, action: str, summary: str, args: dict,
    run: Callable[[bool], Awaitable[dict]], *, guard_own_dialog: bool = False, dedupe_key: str = "",
) -> dict:
    remote = federated.is_remote(info)
    own = not remote and (info.tmux_session == caller.tmux_name or info.session.id in (caller.session_id, caller.current_session_id))
    if remote:
        summary = f"on {info.host_label}: {summary}"
    elif own:
        if not (guard_own_dialog and await _own_dialog_open(_request(manager).app, info)):
            return await run(False)
        summary = f"YOUR OWN open dialog: {summary}"
        return await park(manager, caller, info.session.id, info.tmux_session or "", action, summary, args, run,
                          dedupe_key, beast_eligible=False)
    usage = in_use_mod.summarize(info, _request(manager).app.state.services.registry) if action in in_use_mod.IN_USE_ACTIONS else None
    if not in_use_mod.blocks_beast(usage, action) and beast_mode.approval_skip(action):
        return await beast_mode.run_unprompted(
            caller, action, lambda: _with_usage(run(True), usage), target_id=info.session.id,
            target_tmux=info.tmux_session or "", summary=summary, args=args,
        )
    if not remote and not own and not caller.external and not gate_enabled():
        return await run(False)
    return await park(manager, caller, info.session.id, info.tmux_session or "", action, summary, args, run, dedupe_key,
                      in_use=usage)


async def _with_usage(running: Awaitable[dict], usage: Optional[dict]) -> dict:
    result = await running
    if usage and isinstance(result, dict):
        result = {**result, "in_use": usage, "warning": in_use_mod.warning(usage)}
    return result


async def park(
    manager: Any, caller: AgentCaller, target_id: str, target_tmux: str, action: str, summary: str, args: dict,
    run: Callable[[bool], Awaitable[dict]], dedupe_key: str = "", beast_eligible: bool = True,
    confirm_text: str = "", in_use: Optional[dict] = None, supersede: bool = False,
) -> dict:
    epoch, name = await approval_runtime.pin(manager, target_id)
    replay = call_context.take_replay()
    if replay is not None:
        why = approval_runtime.mismatch(replay, action=action, target_id=target_id, target_tmux=target_tmux,
                                        epoch=epoch, args=args, dedupe_key=dedupe_key)
        if why:
            replay.refused = why
            raise ToolError(why)
        return await _as_result(run(True))
    if beast_eligible and not confirm_text and not in_use_mod.blocks_beast(in_use, action) and beast_mode.approval_skip(action):
        return await beast_mode.run_unprompted(caller, action, lambda: _as_result(run(True)), target_id=target_id,
                                               target_tmux=target_tmux, summary=summary, args=args)
    call = call_context.CURRENT.get()
    extra = {"caller_env_id": caller.session_id, "target_epoch": epoch, "target_name": name,
             "tool": call.tool if call is not None else "", "tool_args": call.args if call is not None else {},
             "plain": wording.plain(action, args, name or target_tmux, summary),
             "confirm_text": confirm_text, "in_use": in_use or {}}
    try:
        item = pending.get_store().create(
            caller_session_id=caller.current_session_id, caller_tmux=caller.tmux_name,
            target_session_id=target_id, target_tmux=target_tmux,
            action=action, args_summary=summary, execute=lambda: _as_result(run(True)), args=args,
            dedupe_key=dedupe_key, external_client=caller.token_name,
            beast_eligible=beast_eligible and not confirm_text and not in_use_mod.blocks_beast(in_use, action), extra=extra,
            supersede=supersede,
        )
    except pending.PendingLimitError as exc:
        raise ToolError(str(exc)) from exc
    logger.info("mcp_action_pending", id=item.id, action=action, caller=caller.tmux_name, client=caller.token_name or None,
                target=target_tmux)
    wait = 0 if (in_use and in_use["in_flight"]) or getattr(manager, "gate_waited", False) else pending.MAX_WAIT_SECONDS
    manager.gate_waited = True
    return _item_result(item, await pending.wait_for(item, wait))


def _item_result(item: pending.PendingAction, status: str) -> dict:
    if status == pending.APPROVED and item.result is not None:
        return item.result
    if status == pending.DENIED:
        raise ToolError("the owner denied this action")
    if status == pending.REFUSED:
        raise ToolError(f"refused when the owner approved: {item.reason}; nothing was done")
    if item.in_use:
        return _ok({"status": "pending", "id": item.id, "in_use": item.in_use, "warning": in_use_mod.warning(item.in_use)})
    return _ok({"status": "pending", "id": item.id})


async def session_send_keys(manager: Any, caller: AgentCaller, args: dict) -> dict:
    info = await session_target.live_info(manager, args, "session_send_keys")
    data, shown = _keys_payload(args)
    epoch = info.session.tmux_created_epoch
    summary = f"type {len(shown['text'])} chars of text and press {shown['keys'] or 'no keys'}"
    run = ((lambda approved: _do_send_keys_remote(info.session.id, epoch, data)) if federated.is_remote(info)
           else (lambda approved: _do_send_keys(_request(manager).app, info.session.id, epoch, data)))
    return await _gated(manager, caller, info, "session_send_keys", summary, shown, run,
                        guard_own_dialog=True, dedupe_key=hashlib.sha256(data).hexdigest())


async def session_restart(manager: Any, caller: AgentCaller, args: dict) -> dict:
    extra = sorted(set(args) - {"target", *restart_account_args.PROPERTIES})
    if extra:
        raise ToolError(f"session_restart does not take {', '.join(extra)}")
    account, pin = restart_account_args.read(args)
    target = await session_target.resolve_target(manager, args, reach=session_target.CLOSED, tool="session_restart")
    if not target.live:
        from src.core.mcp.session_control_tools import WRITE_TOOLS as CONTROL_WRITES

        return await CONTROL_WRITES["session_wake"][3](
            manager, caller, {"target": target.session_uuid, **{k: args[k] for k in restart_account_args.PROPERTIES if k in args}})
    info = target.info
    await restart_account_args.refuse_bad(account, pin, info.session.agent_type, remote=federated.is_remote(info))
    epoch = info.session.tmux_created_epoch
    remote = federated.is_remote(info)
    was_live = federated.pane_live(info) if remote else await _pane_live(_request(manager).app, info)
    summary = ("restart: the pane is LIVE, so this KILLS the running agent and resumes it"
               if was_live else "restart the exited agent as a resume") + restart_account_args.shown(account, pin)
    run = ((lambda approved: _do_restart_remote(info.session.id, epoch, approved, was_live)) if remote
           else (lambda approved: _do_restart(_request(manager).app, info.session.id, epoch, approved, was_live, account, pin)))
    return await _gated(manager, caller, info, "session_restart", summary,
                        {"pane_live": was_live, **({"account": account, "always_use_account": pin} if account else {})}, run)


async def session_stop(manager: Any, caller: AgentCaller, args: dict) -> dict:
    info = await session_target.live_info(manager, args, "session_stop")
    epoch = info.session.tmux_created_epoch
    run = ((lambda approved: _do_stop_remote(info.session.id, epoch)) if federated.is_remote(info)
           else (lambda approved: _do_stop(_request(manager).app, info.session.id, epoch)))
    return await _gated(manager, caller, info, "session_stop", "stop (sleep) the session", {}, run)


async def approval_wait(manager: Any, caller: AgentCaller, args: dict) -> dict:
    item = pending.get_store().get(str(args.get("id", "")))
    if item is None or item.caller_tmux != caller.tmux_name:
        raise ToolError("no such pending action for you (a decision is kept for a day, then cleared)")
    timeout = args.get("timeout", pending.MAX_WAIT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
        raise ToolError("timeout must be a number of seconds")
    return _item_result(item, await pending.wait_for(item, min(timeout, pending.MAX_WAIT_SECONDS)))


_KEYS_SCHEMA = {
    "text": {"type": "string", "maxLength": MAX_KEYS_TEXT, "description": "Literal text, no control characters."},
    "keys": {"type": "array", "maxItems": MAX_KEY_NAMES, "items": {"type": "string", "enum": list(NAMED_KEYS)}},
}

TOOLS: dict[str, tuple[str, dict, list, Callable[..., Awaitable[dict]]]] = {
    "session_notes_put": (
        "Replace a session's markdown note. Send the revision session_notes_get returned.",
        {"target": _TARGET_SCHEMA, "body": {"type": "string"}, "expected_revision": {"type": "integer", "minimum": 0}},
        ["target", "body", "expected_revision"], session_notes_put,
    ),
    "session_create": (
        "Start a new session in a folder or project (on a paired computer: peer plus working_dir there; waits for the owner). Limits: 5 live sessions per agent, 20 in total.",
        {"working_dir": {"type": "string"}, "project": {"type": "string"}, "peer": {"type": "string"},
         "agent_type": {"type": "string"},
         "launch_profile": {"type": "string", "description": "A launch profile id from launch_profiles_list; with agent_type they must agree."},
         "name": {"type": "string"},
         "account": {"type": "string", "description": "A claude account id from launch_accounts_list; the agent launches on it instead of the active account. Not with peer."},
         "always_use_account": {"type": "boolean", "description": "With account: save it as this agent's account (restarts and wakes use it)."}},
        [], session_create,
    ),
    "session_send_message": (
        "Send a message to an agent session's prompt and submit it. Refused while a dialog is open.",
        {"target": _TARGET_SCHEMA, "text": {"type": "string", "maxLength": MAX_MESSAGE_CHARS}},
        ["target", "text"], session_send_message,
    ),
    "session_send_keys": (
        "Type text and press named keys in a session. Aimed at another session, or any session on a paired computer, it waits for the owner's approval.",
        {"target": _TARGET_SCHEMA, **_KEYS_SCHEMA}, ["target"], session_send_keys,
    ),
    "session_restart": (
        "Restart a session's agent as a resume; an asleep or exited one (sessions_list include_asleep), or a closed one with a conversation (include_closed, by session_uuid), is woken the same way. account (with always_use_account) resumes it on that claude account, this computer's sessions only. Aimed at another session, or any session on a paired computer, it waits for the owner's approval.",
        {"target": _TARGET_SCHEMA, **restart_account_args.PROPERTIES}, ["target"], session_restart,
    ),
    "session_stop": (
        "Put a session to sleep (the row stays). Aimed at another session, or any session on a paired computer, it waits for the owner's approval.",
        {"target": _TARGET_SCHEMA}, ["target"], session_stop,
    ),
}

READ_TOOLS: dict[str, tuple[str, dict, list, Callable[..., Awaitable[dict]]]] = {
    "approval_wait": (
        "Wait (up to 50 s) for the decision on a pending action you started.",
        {"id": {"type": "string"}, "timeout": {"type": "number", "minimum": 0, "maximum": pending.MAX_WAIT_SECONDS}},
        ["id"], approval_wait,
    ),
}
