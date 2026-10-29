from __future__ import annotations

from src.core.tmux_control.tmux_error import TmuxError

__all__ = ["SessionError", "SessionNotFound", "SessionNotRunning", "SessionCreateFailed", "SessionInputFailed", "TmuxError"]


class SessionError(ValueError):
    pass


class SessionNotFound(SessionError, LookupError):
    pass


class SessionNotRunning(SessionError):
    pass


class SessionCreateFailed(SessionError):
    pass


class SessionInputFailed(SessionError):
    pass
