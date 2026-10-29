from __future__ import annotations

from typing import Optional

TARGET_SEPARATORS: tuple[str, ...] = (":", ".")


def check_target_name(session_name: str) -> str:
    if any(sep in session_name for sep in TARGET_SEPARATORS):
        raise ValueError(
            f"unsafe tmux session name {session_name!r}: "
            f"contains ':' or '.' which tmux parses as target separators"
        )
    return session_name


def exact_pane_target(session_name: str, pane: Optional[str] = None) -> str:
    return f"={check_target_name(session_name)}:{pane or ''}"


def exact_session_target(session_name: str) -> str:
    return f"={check_target_name(session_name)}"
