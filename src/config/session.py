
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """Session backend configuration.

    - ``backend``: ``"auto"`` (tmux if available, else pty), ``"tmux"``, or ``"pty"``.
    - ``tmux_socket_name``: name passed to ``tmux -L <name>``. Defaults to
      ``"cloude"`` so we never touch the user's default tmux server.
    - ``scrollback_lines``: how many lines the backend captures on re-attach
      for scrollback replay. This is the ATTACH REPLAY DEPTH, not what tmux
      retains - tmux holds ``tmux_backend.HISTORY_LIMIT`` lines and this
      says how many of them are sent to the browser on a reconnect. The two
      ceilings are deliberately different: replaying 50000 lines of ANSI
      into xterm.js is 5-15 MB through the parser, which is felt on a
      phone, so the pane keeps the deeper history and the attach sends a
      bounded slice of it. Anything past ~10000 should be paged rather
      than sent as one blob.
    - ``disable_alternate_screen``: when on, Claude launches receive
      ``CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1`` and Codex launches receive
      ``--no-alt-screen``, so tmux and xterm.js can accumulate real
      scrollback. It is on by default because on the
      alternate screen there is no scrollback to accumulate anywhere in
      the chain - tmux keeps zero history for such a pane no matter how
      high ``history-limit`` is set, and xterm.js applies its own
      ``scrollback`` to the normal buffer only. Turn it off to get Claude
      Code's flicker-free fullscreen renderer back, at the cost of having
      no scrollback at all.
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
