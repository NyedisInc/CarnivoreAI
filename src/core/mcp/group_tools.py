
from __future__ import annotations

from typing import Any, Optional

from src.core.mcp import federated
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _local_infos, _ok
from src.core.mcp.write_tools import _request, _via_route

MAX_MOVE_TARGETS = 50


def _group_of(groups: list, ref: Any) -> Any:
    if not isinstance(ref, str) or not ref.strip():
        raise ToolError("group is required: a group_uuid or name from session_groups_list")
    ref = ref.strip()
    for group in groups:
        if group.group_uuid == ref:
            return group
    named = [g for g in groups if g.name.casefold() == ref.casefold()]
    if len(named) > 1:
        raise ToolError(f"{len(named)} groups are named {ref!r}; use the group_uuid from session_groups_list")
    if not named:
        raise ToolError(f"no group matches {ref!r}; see session_groups_list")
    return named[0]


async def _groups(route_call: Any = None) -> list:
    from src.api import session_groups_routes as routes

    listed = route_call if route_call is not None else await routes.list_session_groups()
    if listed.status != routes.STATUS_OK:
        raise ToolError(f"the groups cannot be read: {listed.detail or listed.status}")
    return listed.groups


def _shape(group: Any, names: dict) -> dict:
    members = [{"name": n, "id": names.get(n)} for n in group.members]
    return {"group_uuid": group.group_uuid, "name": group.name, "position": group.position,
            "members": members, "other_members": max(0, len(group.member_session_uuids) - len(members))}


async def _shaped(manager: Any, groups: list) -> list:
    names = {i.tmux_session: i.session.id for i in await _local_infos(manager) if i.tmux_session}
    return [_shape(g, names) for g in groups]


def _name_arg(args: dict) -> str:
    value = args.get("name")
    if not isinstance(value, str) or not value.strip():
        raise ToolError("name is required and must be non-empty text")
    return value.strip()


def _only(args: dict, allowed: set, tool: str) -> None:
    if set(args) - allowed:
        raise ToolError(f"{tool} takes only {', '.join(sorted(allowed))}")


async def session_groups_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _only(args, set(), "session_groups_list")
    return _ok({"groups": await _shaped(manager, await _groups())})


async def session_group_create(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_groups_routes as routes

    _only(args, {"name"}, "session_group_create")
    name = _name_arg(args)
    before = {g.group_uuid for g in await _groups()}
    listed = await _via_route(routes.create_session_group(routes.CreateGroupRequest(name=name), _request(manager)))
    groups = await _groups(listed)
    shaped = await _shaped(manager, groups)
    fresh = [g for g in shaped if g["group_uuid"] not in before]
    return _ok({"group": fresh[0] if fresh else None, "groups": shaped})


async def session_group_move(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_groups_routes as routes

    _only(args, {"targets", "group"}, "session_group_move")
    targets = args.get("targets")
    if not isinstance(targets, list) or not targets or not all(isinstance(t, str) for t in targets):
        raise ToolError("targets is required: a non-empty list of sessions")
    if len(targets) > MAX_MOVE_TARGETS:
        raise ToolError(f"targets is over the {MAX_MOVE_TARGETS} session limit")
    if "group" not in args:
        raise ToolError("group is required: a group_uuid or name, or null to ungroup")
    groups = await _groups()
    group = None if args["group"] is None else _group_of(groups, args["group"])
    from src.core.mcp import session_target

    resolver = session_target.TargetResolver(manager, _infos=await _local_infos(manager))
    names: list = []
    for target in targets:
        found = await resolver.resolve(target, reach=session_target.STORED, tool="session_group_move")
        name = found.info.tmux_session if found.live else found.tmux_name
        if (found.live and federated.is_remote(found.info)) or not name:
            raise ToolError(f"{target!r} is not a session on this computer with a tmux name")
        if name not in names:
            names.append(name)
    listed = None
    for name in names:
        listed = await _via_route(routes.assign_session_group(
            routes.AssignRequest(tmux_name=name, group_uuid=None if group is None else group.group_uuid),
            _request(manager)))
    shaped = await _shaped(manager, await _groups(listed))
    return _ok({"moved": names, "group": None if group is None else group.name, "groups": shaped})


async def session_group_rename(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_groups_routes as routes

    _only(args, {"group", "name"}, "session_group_rename")
    name = _name_arg(args)
    group = _group_of(await _groups(), args.get("group"))
    listed = await _via_route(routes.rename_session_group(group.group_uuid, routes.RenameGroupRequest(name=name), _request(manager)))
    shaped = await _shaped(manager, await _groups(listed))
    return _ok({"group": next((g for g in shaped if g["group_uuid"] == group.group_uuid), None), "groups": shaped})


async def session_group_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_groups_routes as routes

    _only(args, {"group"}, "session_group_delete")
    group = _group_of(await _groups(), args.get("group"))
    if group.members or group.member_session_uuids:
        raise ToolError(f"group {group.name!r} still has members; move them out with session_group_move (group null) first")
    listed: Optional[Any] = await _via_route(routes.delete_session_group(group.group_uuid, _request(manager)))
    return _ok({"deleted": group.name, "groups": await _shaped(manager, await _groups(listed))})


_GROUP = {"type": "string", "description": "group_uuid or exact group name from session_groups_list"}

READ_TOOLS: dict = {
    "session_groups_list": (
        "List the drawer's session groups (the sidebar's named buckets) with each member's tmux name and session id.",
        {}, [], session_groups_list,
    ),
}

WRITE_TOOLS: dict = {
    "session_group_create": (
        "Create an empty drawer group with a name. Every open drawer updates live. Then use session_group_move to fill it.",
        {"name": {"type": "string", "description": "the group's label"}}, ["name"], session_group_create,
    ),
    "session_group_move": (
        "Move sessions on this computer into a drawer group, or out of every group (group null). Stored by session_uuid, "
        "so a tmux rename keeps the filing. Nothing moves unless every target resolves.",
        {"targets": {"type": "array", "items": _TARGET_SCHEMA, "minItems": 1, "maxItems": MAX_MOVE_TARGETS,
                     "description": "session ids, adopted:<name> or tmux names"},
         "group": {"type": ["string", "null"], "description": "group_uuid or name; null removes from all groups"}},
        ["targets", "group"], session_group_move,
    ),
    "session_group_rename": (
        "Rename a drawer group. Its members and position are untouched.",
        {"group": _GROUP, "name": {"type": "string", "description": "the new label"}}, ["group", "name"], session_group_rename,
    ),
    "session_group_delete": (
        "Delete an empty drawer group. A group that still has members is refused: move them out first (session_group_move, group null).",
        {"group": _GROUP}, ["group"], session_group_delete,
    ),
}
