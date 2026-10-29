
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionMoveRequest(BaseModel):
    """Body of a session move. Exactly one of ``project_id`` and ``new_folder``.

    ``apply`` false answers the plan and changes nothing. With ``apply``, a running session is moved
    only with ``confirm_restart_live``: its agent is stopped and resumed in the new folder.
    """

    project_id: Optional[int] = Field(None, description="An existing project to move the session into")
    new_folder: Optional[str] = Field(
        None, description="A folder to move the session into; created when missing (its parent must exist)")
    apply: bool = Field(False, description="Run the move; false answers the plan only")
    confirm_restart_live: bool = Field(
        False, description="The user confirmed the running agent is stopped and resumed in the new folder")


class SessionMoveResponse(BaseModel):
    """The plan for a session move, and what was done when it was applied.

    ``refusals`` lists every reason the move may not run (``code``, ``message``); ``ok`` is true only
    with none. ``kills_live_pane`` says an apply needs ``confirm_restart_live``. ``done`` is set after an apply.
    """

    session_uuid: str
    tmux_name: Optional[str] = None
    source: Optional[str] = None
    source_kind: Optional[str] = Field(None, description="'temp' (files are carried) or 'home' (none are)")
    destination: Optional[str] = None
    destination_kind: Optional[str] = Field(None, description="'project' or 'new_folder'")
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    creates_folder: bool = False
    claude_session_uuid: Optional[str] = None
    pane_state: str = "unknown"
    kills_live_pane: bool = False
    file_count: int = 0
    total_bytes: int = 0
    left_behind: List[str] = Field(default_factory=list)
    collisions: List[str] = Field(default_factory=list)
    ok: bool = False
    refusals: List[Dict[str, str]] = Field(default_factory=list)
    applied: bool = False
    done: Optional[Dict[str, Any]] = None
