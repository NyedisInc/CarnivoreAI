"""Where a session's pane is right now: its folder, what it runs, its size.

FLAT, ONE LEVEL, NO WRAPPER, for the same gotcha-1 reason as
``session_token_usage.py``. EVERY FIELD IS OPTIONAL AND ``None`` MEANS
"could not be read", never a default: a pane tmux did not answer for has
no cwd, not an empty one. The shell foot bar under a terminal component
(issue #623) draws only the fields that are present.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SessionPaneFacts(BaseModel):
    """Cheap, live facts about one session's active pane.

    Example: SessionPaneFacts(cwd='/Users/a/src/app', cwd_display='~/src/app',
      command='zsh', git_branch='master', cols=177, rows=60)
    """

    cwd: Optional[str] = Field(None, description="tmux #{pane_current_path}, absolute")
    cwd_display: Optional[str] = Field(None, description="cwd with the home directory written as ~")
    command: Optional[str] = Field(None, description="tmux #{pane_current_command}, the foreground program")
    git_branch: Optional[str] = Field(
        None, description="branch named by the cwd's .git/HEAD, or a short sha when detached"
    )
    cols: Optional[int] = Field(None, description="tmux #{pane_width}")
    rows: Optional[int] = Field(None, description="tmux #{pane_height}")
