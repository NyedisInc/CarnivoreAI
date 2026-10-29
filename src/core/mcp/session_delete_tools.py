
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.core.mcp import drawer_pins, federated, in_use, session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _ok
from src.core.mcp.write_tools import _request, _resolved_again, _via_route, park


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

    row = await session_target.TargetResolver(manager).asleep_row(uuid, uuid_only=True)
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

    async def run(approved: bool) -> dict:
        return await _do_delete_asleep(manager, uuid, row_id)

    return await park(manager, caller, uuid, "", "session_delete",
                      f"DELETE asleep session {name} (nothing is running; its record leaves your lists and any pin is removed)",
                      {}, run, dedupe_key=f"session_delete:{uuid}", beast_eligible=False)


async def session_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    if set(args) - {"target"}:
        raise ToolError("session_delete takes only target")
    target = await session_target.resolve_target(manager, args, reach=session_target.STORED, tool="session_delete")
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
    return await park(manager, caller, info.session.id, info.tmux_session or "", "session_delete",
                      f"DELETE session {name} (its tmux session is killed)", {}, run,
                      dedupe_key=f"session_delete:{info.session.id}", beast_eligible=False,
                      in_use=in_use.summarize(info, app.state.services.registry))


WRITE_TOOLS: dict = {
    "session_delete": (
        "Delete a session (kills its tmux session), or an ASLEEP one by session_uuid or tmux name (its record leaves your lists, it is unpinned, nothing is killed). Always waits for the owner's approval, even in Beast mode. Refuses your own session and a paired computer's.",
        {"target": _TARGET_SCHEMA}, ["target"], session_delete,
    ),
}
