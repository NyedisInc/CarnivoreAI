
from __future__ import annotations

from typing import Optional

from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.launch_profiles.installed import harness_installed
from src.core.sessions.errors import SessionCreateFailed, TmuxError

_NOT_INSTALLED_CODES = {"claude": "agent_not_installed_claude", "codex": "agent_not_installed_codex"}


def classify_launch_failure(
    exc: BaseException,
    agent_type: Optional[str],
    *,
    resolved_harness: Optional[str] = None,
) -> str:
    text = str(exc)
    if isinstance(exc, TmuxError) and text.startswith("tmux was not found"):
        return "tmux_missing"
    if isinstance(exc, SessionCreateFailed) and isinstance(exc.__cause__, OSError):
        return "workdir_unusable"
    if isinstance(exc, TmuxError) and text.startswith("agent failed to launch"):
        harness = resolved_harness or agent_type or "claude"
        if harness in AGENT_FAMILY_BY_NAME and not harness_installed(harness):
            return _NOT_INSTALLED_CODES.get(harness, "agent_not_installed")
        return "agent_exited"
    return "session_launch_failed"
