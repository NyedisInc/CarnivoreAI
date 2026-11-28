
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.core.mcp import beast_mode, drawer_pins, federated, in_use, session_creators, session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _ok
from src.core.mcp.write_tools import _request, _resolved_again, _via_route, park


CREATOR_REASON = "the asking agent created this session"


async def _run_by_creator(caller: AgentCaller, target_id: str, target_tmux: str, label: str, run: Any) -> dict:
    return await beast_mode.run_unprompted(caller, "session_delete", run, target_id=target_id, target_tmux=target_tmux,
                                           summary=f"DELETE {label} ({CREATOR_REASON})",
                                           event="mcp_session_deleted_by_its_creator", approval_source=CREATOR_REASON)


def _is_own(info: Any, caller: AgentCaller) -> bool:
    return info.tmux_session == caller.tmux_name or info.session.id in (caller.session_id, caller.current_session_id)


async def _do_delete(app: Any, target_id: str, epoch: Any) -> dict:
    from src.api import session_attach_routes, session_crud_routes

    info = await _resolved_again(app, target_id, epoch)
    request = SimpleNamespace(app=app)
    registry = app.state.services.registry
    if registry.resolve_session_id(info.session.id):
        await _via_route(session_crud_routes.destroy_session(request, session_id=info.session.id))
    elif info.tmux_session:
        await _via_route(session_attach_routes.destroy_external_session(request, info.tmux_session))
    else:
        raise ToolError("that session has no tmux name to delete")
    return _ok({"deleted": True, "session": info.tmux_session or info.session.id})


async def _do_delete_asleep(manager: Any, uuid: str, row_id: Any) -> dict:
    from src.api import session_records_routes

    resolver = session_target.TargetResolver(manager)
    row = await resolver.asleep_row(uuid, uuid_only=True) or await resolver.stopped_row(uuid)
    if not row or row["id"] != row_id:
        raise ToolError("the target is no longer the same asleep session; nothing was done")
    request = _request(manager)
    await _via_route(session_records_routes.delete_session_record(request, uuid))
    try:
        pinned = await drawer_pins.write_pinned(request, lambda cur: [u for u in cur if u != uuid])
    except ToolError as exc:
        raise ToolError(f"the asleep session was deleted but could not be unpinned: {exc}") from exc
    return _ok({"deleted": True, "asleep": True, "session": row.get("tmux_name") or uuid,
                "unpinned": uuid not in pinned})


async def _delete_asleep(manager: Any, caller: AgentCaller, row: dict) -> dict:
    uuid, row_id = str(row["session_uuid"]), row["id"]
    name = row.get("tmux_name") or uuid
    if await session_creators.created_by_caller(manager, caller, uuid):
        return await _run_by_creator(caller, uuid, "", f"asleep session {name}",
                                     lambda: _do_delete_asleep(manager, uuid, row_id))

    async def run(approved: bool) -> dict:
        return await _do_delete_asleep(manager, uuid, row_id)

    return await park(manager, caller, uuid, "", "session_delete",
                      f"DELETE asleep session {name} (nothing is running; its record leaves your lists and any pin is removed)",
                      {}, run, dedupe_key=f"session_delete:{uuid}", beast_eligible=False)


async def session_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    if set(args) - {"target"}:
        raise ToolError("session_delete takes only target")
    target = await session_target.resolve_target(manager, args, reach=session_target.RECORD, tool="session_delete")
    if not target.live:
        return await _delete_asleep(manager, caller, target.row)
    info = target.info
    if federated.is_remote(info):
        raise ToolError("that session lives on a paired computer: call session_delete there")
    if _is_own(info, caller):
        raise ToolError("you cannot delete your own session")
    epoch = info.session.tmux_created_epoch
    app = _request(manager).app

    async def run(approved: bool) -> dict:
        return await _do_delete(app, info.session.id, epoch)

    name = info.tmux_session or info.session.id
    usage = in_use.summarize(info, app.state.services.registry)
    if (not in_use.blocks_beast(usage, "session_delete") and info.activity_status not in (None, "", "unknown")
            and await session_creators.created_by_caller(manager, caller, info.session_uuid)):
        fresh = await _resolved_again(app, info.session.id, epoch)
        fresh_usage = in_use.summarize(fresh, app.state.services.registry)
        if not in_use.blocks_beast(fresh_usage, "session_delete") and fresh.activity_status not in (None, "", "unknown"):
            return await _run_by_creator(caller, info.session.id, info.tmux_session or "", f"session {name}",
                                         lambda: run(True))
        usage = fresh_usage
    return await park(manager, caller, info.session.id, info.tmux_session or "", "session_delete",
                      f"DELETE session {name} (its tmux session is killed)", {}, run,
                      dedupe_key=f"session_delete:{info.session.id}", beast_eligible=False, in_use=usage)


WRITE_TOOLS: dict = {
    "session_delete": (
        "Delete a session (kills its tmux session). A stopped one (asleep or any stopped record) by session_uuid, or an asleep one by tmux name, only leaves your lists unpinned; nothing is killed. Always waits for owner approval, even in Beast mode, except a session YOU made with session_create and no work running: deleted at once and logged. Refuses your own session and a paired computer's.",
        {"target": _TARGET_SCHEMA}, ["target"], session_delete,
    ),
}
