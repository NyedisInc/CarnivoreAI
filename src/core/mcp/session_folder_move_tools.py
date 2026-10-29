
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from src.core.mcp import federated, in_use, session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _ok
from src.core.mcp.write_tools import _request, _via_route, park
from src.models.session_move import SessionMoveRequest, SessionMoveResponse

_ARGS = frozenset({"target", "project_id", "new_folder"})


def _body(args: dict, *, apply: bool, confirm_restart_live: bool = False) -> SessionMoveRequest:
    project_id, new_folder = args.get("project_id"), args.get("new_folder")
    if isinstance(project_id, bool) or (project_id is not None and not isinstance(project_id, int)):
        raise ToolError("project_id must be a whole number")
    if new_folder is not None and (not isinstance(new_folder, str) or not new_folder.strip()):
        raise ToolError("new_folder must be non-empty text")
    if (project_id is None) == (new_folder is None):
        raise ToolError("give exactly one of project_id and new_folder")
    return SessionMoveRequest(project_id=project_id, new_folder=new_folder, apply=apply,
                              confirm_restart_live=confirm_restart_live)


async def _plan(manager: Any, uuid: str, args: dict) -> SessionMoveResponse:
    from src.api import session_move_routes

    return await _via_route(session_move_routes.move_session_folder(
        uuid, _body(args, apply=False), SimpleNamespace(app=_request(manager).app)))


def _refusal_text(plan: SessionMoveResponse) -> str:
    return "; ".join(str(r.get("message") or r.get("code")) for r in plan.refusals) or "the move is not allowed"


async def _do_move(manager: Any, uuid: str, args: dict, asked: SessionMoveResponse) -> dict:
    from src.api import session_move_routes

    fresh = await _plan(manager, uuid, args)
    if not fresh.ok:
        raise ToolError(f"the move is no longer allowed: {_refusal_text(fresh)}; nothing was done")
    if (fresh.destination, fresh.kills_live_pane, fresh.file_count) != (asked.destination, asked.kills_live_pane,
                                                                        asked.file_count):
        raise ToolError("the session or the folders changed since the owner was asked; nothing was moved")
    answer = await _via_route(session_move_routes.move_session_folder(
        uuid, _body(args, apply=True, confirm_restart_live=asked.kills_live_pane),
        SimpleNamespace(app=_request(manager).app)))
    return _ok(answer.model_dump())


def _summary(plan: SessionMoveResponse) -> str:
    carried = f"{plan.file_count} file(s) move" if plan.file_count else "no file moves"
    live = "; its RUNNING agent is stopped and resumed there" if plan.kills_live_pane else "; its agent has exited"
    return f"move session {plan.tmux_name or plan.session_uuid} to {plan.destination} ({carried}{live})"


async def session_folder_move(manager: Any, caller: AgentCaller, args: dict) -> dict:
    extra = sorted(set(args) - _ARGS)
    if extra:
        raise ToolError(f"session_folder_move does not take {', '.join(extra)}; it takes target, project_id, new_folder")
    _body(args, apply=False)
    resolver = session_target.TargetResolver(manager)
    target = await resolver.resolve(args, reach=session_target.LIVE, tool="session_folder_move")
    info = target.info
    if federated.is_remote(info):
        raise ToolError("that session lives on a paired computer: call session_folder_move there")
    if info.tmux_session == caller.tmux_name or info.session.id in (caller.session_id, caller.current_session_id):
        raise ToolError("you cannot move your own session: its pane is the one that is restarted")
    uuid = await resolver.uuid_of(target)
    plan = await _plan(manager, uuid, args)
    if not plan.ok:
        raise ToolError(f"cannot move: {_refusal_text(plan)}")

    async def run(approved: bool) -> dict:
        return await _do_move(manager, uuid, args, plan)

    usage: Optional[dict] = (in_use.summarize(info, _request(manager).app.state.services.registry)
                             if plan.kills_live_pane else None)
    return await park(manager, caller, info.session.id, info.tmux_session or "", "session_folder_move", _summary(plan),
                      {"pane_live": plan.kills_live_pane, "destination": plan.destination,
                       "file_count": plan.file_count},
                      run, dedupe_key=f"session_folder_move:{uuid}:{plan.destination}", in_use=usage)


WRITE_TOOLS: dict = {
    "session_folder_move": (
        "Move a session out of its temp folder (ses_ or home) into a project or new folder on this computer, resuming the same conversation there. Not session_move (that goes to another computer). Waits for the owner's approval; refuses your own session.",
        {"target": _TARGET_SCHEMA,
         "project_id": {"type": "integer", "description": "An existing project to move into (projects_list). Exactly one of project_id and new_folder."},
         "new_folder": {"type": "string", "description": "A folder to move into; created when missing (its parent must exist)."}},
        ["target"], session_folder_move,
    ),
}
