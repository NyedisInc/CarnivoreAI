
from __future__ import annotations

from typing import Any

from src.core.mcp import federated, session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _request, _via_route

_REV = {"expected_revision": {"type": "integer", "minimum": 0,
                              "description": "the layout revision layouts_list returned; omit to skip the check"}}
_LAYOUT = {"type": "string", "description": "layout_uuid or exact layout name from layouts_list"}
_SESSION = {"type": "string", "description": "session id (ses_...), adopted:<name>, tmux name, session_uuid, or the agent's name"}


def _only(args: dict, allowed: set, tool: str) -> None:
    if set(args) - allowed:
        raise ToolError(f"{tool} takes only {', '.join(sorted(allowed))}")


def _revision(args: dict) -> Any:
    value = args.get("expected_revision")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ToolError("expected_revision must be a non-negative integer")
    return value


async def _layouts() -> list:
    from src.api.layouts_routes import STATUS_OK, list_layouts

    listed = await _via_route(list_layouts())
    if listed.status != STATUS_OK:
        raise ToolError(f"the layouts cannot be read: {listed.detail or listed.status}")
    return listed.layouts


def _layout_of(layouts: list, ref: Any) -> Any:
    if not isinstance(ref, str) or not ref.strip():
        raise ToolError("layout is required: a layout_uuid or name from layouts_list")
    ref = ref.strip()
    found = next((l for l in layouts if l.layout_uuid == ref), None) or next(
        (l for l in layouts if l.name.casefold() == ref.casefold()), None)
    if found is None:
        known = ", ".join(repr(l.name) for l in layouts[:20]) or "none saved"
        raise ToolError(f"unknown layout {ref[:60]!r}; known layouts: {known}")
    return found


async def _session_uuid_of(manager: Any, ref: Any, tool: str) -> str:
    if not isinstance(ref, str) or not ref.strip():
        raise ToolError("session is required: a session id, tmux name or agent name")
    ref = ref.strip()
    resolver = session_target.TargetResolver(manager)
    try:
        found = await resolver.resolve(ref, reach=session_target.STORED, tool=tool)
    except ToolError as miss:
        from src.core.crosstalk import directory

        result = await directory.lookup(manager, query=ref, include_remote=False, include_self=True)
        cards = result["agents"]
        if len(cards) > 1 or result["ambiguous"]:
            names = "; ".join(f"{c['name']} ({c['id']})" for c in cards[:10])
            raise ToolError(f"{ref!r} matches {len(cards)} agents, pick one by id: {names}") from None
        if not cards or not cards[0].get("session_uuid"):
            raise miss from None
        return str(cards[0]["session_uuid"])
    if found.live and federated.is_remote(found.info):
        raise ToolError(f"{tool} is local only: a paired computer's session cannot join a Layout here")
    return await resolver.uuid_of(found)


def _shape(layout: Any, names: dict) -> dict:
    return {"layout_uuid": layout.layout_uuid, "name": layout.name, "revision": layout.revision,
            "members": [{"session_uuid": m.session_uuid, "name": names.get(m.session_uuid)} for m in layout.members]}


async def _names(manager: Any) -> dict:
    from src.core.mcp.common import _local_infos

    return {i.session_uuid: i.tmux_session for i in await _local_infos(manager) if i.session_uuid}


async def layouts_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _only(args, set(), "layouts_list")
    names = await _names(manager)
    return _ok({"layouts": [_shape(l, names) for l in await _layouts()]})


async def layout_member_add(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.layouts_routes import add_layout_member
    from src.models.layouts import AddMemberRequest

    _only(args, {"layout", "session", "expected_revision"}, "layout_member_add")
    revision = _revision(args)
    layout = _layout_of(await _layouts(), args.get("layout"))
    uuid = await _session_uuid_of(manager, args.get("session"), "layout_member_add")
    names = await _names(manager)
    if any(m.session_uuid == uuid for m in layout.members):
        return _ok({"status": "already_present", "layout": _shape(layout, names)})
    done = await _via_route(add_layout_member(
        layout.layout_uuid, AddMemberRequest(session_uuid=uuid, expected_revision=revision), _request(manager)))
    return _ok({"status": "added", "layout": _shape(done.layout, names) if done.layout else None})


async def layout_member_remove(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.layouts_routes import remove_layout_member

    _only(args, {"layout", "session", "expected_revision"}, "layout_member_remove")
    revision = _revision(args)
    layout = _layout_of(await _layouts(), args.get("layout"))
    uuid = await _session_uuid_of(manager, args.get("session"), "layout_member_remove")
    names = await _names(manager)
    if not any(m.session_uuid == uuid for m in layout.members):
        return _ok({"status": "not_a_member", "layout": _shape(layout, names), "deleted": False, "survivor": None})
    if len(layout.members) <= 2:
        raise ToolError(
            "removing this session would leave one member and delete the whole Layout (name, colour, geometry); "
            "the owner does that in the sidebar's LAYOUTS band")
    done = await _via_route(remove_layout_member(layout.layout_uuid, uuid, _request(manager), revision))
    survivor = done.survivor.session_uuid if done.survivor else None
    return _ok({"status": "removed", "layout": _shape(done.layout, names) if done.layout else None,
                "deleted": done.deleted, "survivor": survivor})


READ_TOOLS: dict = {
    "layouts_list": (
        "List the saved Layouts (the sidebar's LAYOUTS band): layout_uuid, name, revision and each member's session_uuid "
        "and tmux name. A Layout holds terminal sessions only.",
        {}, [], layouts_list,
    ),
}
UNGATED_WRITES: frozenset = frozenset({"layout_member_add", "layout_member_remove"})
WRITE_TOOLS: dict = {
    "layout_member_add": (
        "Add a session (id, tmux name or agent name) to a saved Layout as its last tab; the owner's open windows update live. "
        "Already a member answers already_present. An agent name that matches several agents is refused with the candidates.",
        {"layout": _LAYOUT, "session": _SESSION, **_REV}, ["layout", "session"], layout_member_add,
    ),
    "layout_member_remove": (
        "Take a session off a saved Layout; the session keeps running. A Layout of two members is refused, since that would delete it (the owner does that in the UI). Not a member answers not_a_member.",
        {"layout": _LAYOUT, "session": _SESSION, **_REV}, ["layout", "session"], layout_member_remove,
    ),
}
