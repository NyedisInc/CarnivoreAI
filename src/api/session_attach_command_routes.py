
from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.auth import require_auth
from src.api.remote_route_guard import refuse_remote
from src.core.tmux_discovery import tmux_argv_prefix

router = APIRouter(tags=["session-attach-command"])

MAX_TMUX_NAME_LENGTH = 200

NO_TMUX_SESSION_CODE = "no_tmux_session"


class AttachCommand(BaseModel):
    """The attach command of one local session.

    Fields: argv (list[str]) - run it as is, never through a shell; tmux_session (str) - the stored tmux name;
    socket (str) - the tmux socket name (``-L``); read_only (bool) - the argv attaches with ``-r``.
    """

    argv: List[str]
    tmux_session: str
    socket: str
    read_only: bool = False


def attach_argv(tmux_name: str, socket_name: str, read_only: bool = False) -> List[str]:
    flags = ["-r"] if read_only else ["-f", "ignore-size"]
    return [*tmux_argv_prefix(socket_name), "attach-session", *flags, "-t", "=" + tmux_name]


@router.get("/sessions/{session_id}/attach-command", response_model=AttachCommand, dependencies=[Depends(require_auth)])
async def get_session_attach_command(request: Request, session_id: str, read_only: bool = False) -> AttachCommand:
    """The argv that attaches a terminal to one local session, built from its stored tmux name.

    Inputs: request (Request); session_id (str) - a session row id (created or ``adopted:``); read_only (bool) -
      attach with ``-r`` (Watch in Terminal).
    Output: AttachCommand.
    Raises: HTTPException 404 - no session carries this id; 409 ``remote_host`` - a paired computer's session;
      409 ``no_tmux_session`` - the row has no usable tmux name.
    Example: GET /api/v1/sessions/ses_1/attach-command -> {"argv": ["/opt/homebrew/bin/tmux", "-L", "cloude", ...]}
    """
    manager: Any = request.app.state.session_manager
    refuse_remote(manager, session_id, "the terminal attach command")
    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    name = getattr(info, "tmux_session", None)
    if not isinstance(name, str) or not name or len(name) > MAX_TMUX_NAME_LENGTH or "\0" in name:
        raise HTTPException(status_code=409, detail={
            "code": NO_TMUX_SESSION_CODE,
            "detail": "this session has no tmux session to attach to (asleep, or never started)"})
    socket_name = manager._tmux_socket_name()
    return AttachCommand(argv=attach_argv(name, socket_name, read_only), tmux_session=name, socket=socket_name,
                         read_only=read_only)
