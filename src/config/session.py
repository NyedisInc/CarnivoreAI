
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """Session backend configuration.
    """
    backend: str = Field(
        default="auto",
        description="Session backend: 'auto' | 'tmux' | 'pty'",
    )
    tmux_socket_name: str = Field(
        default="cloude",
        description="Dedicated tmux socket name (tmux -L <name>)",
    )
    scrollback_lines: int = Field(
        default=10000,
        description="Lines of scrollback to capture on re-attach",
        ge=0,
    )
    disable_alternate_screen: bool = Field(
        default=True,
        description=(
            "Launch agents with CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1 so "
            "they render on the normal screen and scrollback accumulates"
        ),
    )
