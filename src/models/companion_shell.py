
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .sessions import Session


class CompanionShell(BaseModel):
    """What ``POST`` and ``GET /sessions/{id}/shell`` answer.

    ``session`` is the shell's own ``Session`` so the terminal client's ``_unwrapSession`` accepts the whole body as
    a SessionInfo-shaped wrapper; the panel attaches to ``session_id`` over ``/ws/terminal``. A session id is NOT a
    tmux name: ``tmux_session`` is the shell's tmux name and nothing derives one from the other.
    """

    agent_session_id: str = Field(..., description="the agent's session id (ses_ or adopted:), as asked")
    agent_row_id: int = Field(..., description="the agent's sessions.id")
    session_id: str = Field(..., description="the shell's session id, for /ws/terminal")
    session_row_id: int = Field(..., description="the shell's sessions.id (the panel keys its slot on it)")
    tmux_session: Optional[str] = Field(None, description="the shell's tmux session name")
    working_dir: str = Field(..., description="the agent row's stored folder, byte for byte")
    state: Literal["created", "existing", "restarted"] = Field(..., description="what this call did")
    pane: Optional[Literal["live", "dead", "unknown"]] = Field(
        None, description="the measured #{pane_dead}; unknown is never collapsed to live")
    session: Optional[Session] = Field(None, description="the shell's Session")
