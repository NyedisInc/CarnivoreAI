
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List, Mapping, Optional

import structlog

from src.core.mcp import channel as channel_events

logger = structlog.get_logger()

OUTCOME_DELIVERED = "delivered"
OUTCOME_RESENT = "resent"
OUTCOME_UNCONFIRMED = "unconfirmed"
CONFIRM_WINDOW_S: float = 10.0
CONFIRM_STEP_S: float = 0.5


def transcript_path(app_state: Any, session_id: str, tmux_name: str) -> Optional[Path]:
    from src.core.session_transcript_presence import conversation_presence  # noqa: PLC0415

    uuid = app_state.session_manager.claude_uuid_for_tmux_name(tmux_name)
    if not uuid:
        return None
    session = app_state.services.registry.get_session(session_id)
    working_dir = session.working_dir if session is not None else None
    return conversation_presence(uuid, working_dir=working_dir).path


def _size(path: Optional[Path]) -> int:
    try:
        return path.stat().st_size if path is not None else 0
    except OSError:
        return 0


def _texts(record: Any) -> List[str]:
    if not isinstance(record, dict):
        return []
    out: List[str] = []
    message = record.get("message")
    for content in (record.get("content"), message.get("content") if isinstance(message, dict) else None):
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            out.extend(str(b.get("text")) for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return out


def body_seen_after(path: Optional[Path], offset: int, body: str) -> bool:
    if path is None:
        return False
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            written = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        logger.warning("channel_delivery_confirm_unreadable", path=str(path), error=type(exc).__name__)
        return False
    wanted = " ".join(body.split())
    for line in written.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if any(wanted in " ".join(text.split()) for text in _texts(record)):
            return True
    return False


async def _seen_within(app_state: Any, session_id: str, tmux_name: str, offset: int, body: str) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CONFIRM_WINDOW_S
    while True:
        path = await asyncio.to_thread(transcript_path, app_state, session_id, tmux_name)
        if await asyncio.to_thread(body_seen_after, path, offset, body):
            return True
        if loop.time() + CONFIRM_STEP_S > deadline:
            return False
        await asyncio.sleep(CONFIRM_STEP_S)


async def push_confirmed(app_state: Any, session_id: str, tmux_name: str, body: str, meta: Mapping[str, str]) -> Optional[str]:
    offset = _size(await asyncio.to_thread(transcript_path, app_state, session_id, tmux_name))
    if not channel_events.REGISTRY.push(tmux_name, body, meta):
        return None
    outcome = OUTCOME_DELIVERED
    if not await _seen_within(app_state, session_id, tmux_name, offset, body):
        if not channel_events.REGISTRY.push(tmux_name, body, meta):
            logger.warning("channel_delivery_outcome", session_id=session_id, outcome=OUTCOME_UNCONFIRMED, reason="resend_declined")
            return OUTCOME_UNCONFIRMED
        outcome = OUTCOME_RESENT if await _seen_within(app_state, session_id, tmux_name, offset, body) else OUTCOME_UNCONFIRMED
    log = logger.warning if outcome == OUTCOME_UNCONFIRMED else logger.info
    log("channel_delivery_outcome", session_id=session_id, tmux_session=tmux_name, outcome=outcome, bytes=len(body.encode()))
    return outcome
