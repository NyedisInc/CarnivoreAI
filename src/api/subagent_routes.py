
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.session_token_usage.reader import SessionSubject
from src.core.subagents.session import read_session_subagents
from src.core.subagents.tally import process_start_for
from src.models.subagents import SessionSubagents

logger = structlog.get_logger()
router = APIRouter()


def process_started_at_for(
    session_manager: Any, session_id: str, conversation_uuid: Optional[str]
) -> Optional[datetime]:
    watcher = session_manager._attention_watcher
    if watcher is None or not conversation_uuid:
        return None
    observation = watcher.observation_for(session_id, now=datetime.now(timezone.utc))
    if observation is None or observation.stale:
        return None
    return process_start_for(observation.evidence.registry, conversation_uuid)


@router.get(
    "/sessions/{session_id}/subagents",
    response_model=SessionSubagents,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_subagents(request: Request, session_id: str) -> SessionSubagents:
    """List the subagents of a session's current conversation, with counts.
    """
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, "the subagents read")
    info = await session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    tmux_name = info.tmux_session
    working_dir = info.session.working_dir if info.session is not None else None
    conversation_uuid = (
        session_manager._claude_uuid_for_tmux_name(tmux_name) if tmux_name else None
    )
    subject = SessionSubject(
        agent_family=info.agent_family,
        conversation_uuid=conversation_uuid,
        working_dir=working_dir,
    )
    row_id = info.session.id if info.session is not None else session_id
    started_at = process_started_at_for(session_manager, row_id, conversation_uuid)
    result = await asyncio.to_thread(
        read_session_subagents, subject, process_started_at=started_at
    )
    logger.debug(
        "session_subagents_read",
        session_id=session_id,
        state=result.state,
        total=result.counts.total if result.counts is not None else None,
        running=result.counts.running if result.counts is not None else None,
        process_start_known=started_at is not None,
    )
    return result
