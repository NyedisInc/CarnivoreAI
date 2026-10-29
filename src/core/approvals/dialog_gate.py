
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.core.approvals.extract import extract_dialog
from src.core.attention_reader import AttentionEvidenceReader
from src.core.session_startup_gate import GATE_READY, startup_screen_kind

logger = structlog.get_logger()

OPEN = "open"
CLEAR = "clear"
UNREADABLE = "unreadable"

AGENT_FAMILIES = frozenset({"claude", "codex"})

Capture = Callable[[str], Awaitable[Optional[str]]]


def is_agent_pane(info: Any) -> bool:
    return info.agent_family in AGENT_FAMILIES


async def _default_capture(manager: Any, tmux_name: str) -> Optional[str]:
    return await asyncio.to_thread(AttentionEvidenceReader._capture, manager.tmux_socket_name(), tmux_name)


async def dialog_verdict(app: Any, session_id: str, *, capture: Optional[Capture] = None) -> str:
    manager = app.state.session_manager
    info = await manager.get_session_info(session_id=session_id)
    if info is None:
        return UNREADABLE
    if info.activity_status == "question":
        return OPEN
    if not is_agent_pane(info):
        return CLEAR
    if info.startup_gate != GATE_READY:
        return OPEN
    tmux_name = info.tmux_session
    if not tmux_name:
        return UNREADABLE
    try:
        text = await (capture(tmux_name) if capture is not None else _default_capture(manager, tmux_name))
    except (OSError, ValueError) as exc:
        logger.warning("dialog_gate_capture_failed", session_id=session_id, error_type=type(exc).__name__)
        return UNREADABLE
    if text is None:
        return UNREADABLE
    if extract_dialog(text, info.agent_family) is not None or startup_screen_kind(text) is not None:
        logger.info("dialog_gate_open", session_id=session_id, source="fresh_capture")
        return OPEN
    return CLEAR
