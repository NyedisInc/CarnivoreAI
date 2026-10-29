
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any

from src.core.mcp import drawer_pins, federated
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _all_infos, _ok
from src.core.mcp.write_tools import _request

LAYOUT_PREFIX = "layout:"


async def _uuid_of(manager: Any, args: dict, tool: str, reach: str) -> tuple[Any, str]:
    from src.core.mcp import session_target

    if set(args) - {"target"}:
        raise ToolError(f"{tool} takes only target")
    resolver = session_target.TargetResolver(manager)
    target = await resolver.resolve(args, reach=reach, tool=tool)
    if target.live and federated.is_remote(target.info):
        raise ToolError("that session lives on a paired computer, which keeps its own pins: call this tool there")
    return target, await resolver.uuid_of(target)


async def pinned_session_uuids(request: Any) -> list:
    _, arrangement = await drawer_pins.read_arrangement(request)
    return [u for u in arrangement.get("pinned") or [] if isinstance(u, str) and not u.startswith(LAYOUT_PREFIX)]


def _names_of(uuids: list) -> dict:
    from src.config import settings
    from src.core.db import connect, db_path_for

    if not uuids:
        return {}
    marks = ",".join("?" for _ in uuids)
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        rows = conn.execute(f"SELECT session_uuid, tmux_name FROM sessions WHERE session_uuid IN ({marks})", uuids).fetchall()
    return {str(u): n for u, n in rows}


async def _set_pin(manager: Any, args: dict, tool: str, pin: bool) -> dict:
    from src.core.mcp import session_target

    target, uuid = await _uuid_of(manager, args, tool, session_target.STORED if pin else session_target.PINNED)
    pinned = await drawer_pins.write_pinned(_request(manager), lambda cur: (cur if uuid in cur else cur + [uuid]) if pin
                                 else [u for u in cur if u != uuid])
    return _ok({"session": target.shown, "session_uuid": uuid, "state": _STATE[target.kind], "pinned": uuid in pinned,
                "pinned_count": len([u for u in pinned if not u.startswith(LAYOUT_PREFIX)])})


async def session_pin(manager: Any, caller: AgentCaller, args: dict) -> dict:
    return await _set_pin(manager, args, "session_pin", True)


async def session_unpin(manager: Any, caller: AgentCaller, args: dict) -> dict:
    return await _set_pin(manager, args, "session_unpin", False)


async def session_pins_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.mcp import session_target

    if args:
        raise ToolError("session_pins_list takes no arguments")
    uuids = await pinned_session_uuids(_request(manager))
    names = await asyncio.to_thread(_names_of, uuids)
    live = {i.tmux_session: i.session.id for i in await _all_infos(manager) if i.tmux_session}
    asleep = {str(r["session_uuid"]) for r in await session_target.TargetResolver(manager).asleep_rows()}
    rows = []
    for u in uuids:
        name = names.get(u)
        state = "live" if name in live else "asleep" if u in asleep else "orphaned"
        rows.append({"name": name, "id": live.get(name) if state == "live" else None, "session_uuid": u,
                     "state": state, "orphaned": state == "orphaned"})
    return _ok({"pinned": rows})


_STATE = {"live": "live", "asleep": "asleep", "orphan_pin": "orphaned"}


READ_TOOLS: dict = {
    "session_pins_list": (
        "List the sessions pinned in the drawer, in pinned-band order: tmux name, session id (null when not live), "
        "session_uuid and state (live, asleep or orphaned: the session is gone but its pin stayed; unpin it by session_uuid).",
        {}, [], session_pins_list,
    ),
}

WRITE_TOOLS: dict = {
    "session_pin": (
        "Pin a session on this computer in the drawer, live or asleep, the same on every device. Stored by session_uuid, so a tmux rename keeps it. "
        "Other drawer order, bands and folds are untouched; open drawers update live.",
        {"target": _TARGET_SCHEMA}, ["target"], session_pin,
    ),
    "session_unpin": (
        "Unpin a session in the drawer, the same on every device: live, asleep, or an orphaned pin whose session is gone "
        "(target its session_uuid from session_pins_list). Other drawer order, bands and folds are untouched.",
        {"target": _TARGET_SCHEMA}, ["target"], session_unpin,
    ),
}
