
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.evidence import observed_conversation_uuid
from src.core.attention.transcript_facts import FACTS_FOUND
from src.core.attention.turn_counts import KIND_SHELL
from src.core.session_token_usage.reader import SessionSubject
from src.core.subagents.parked_work import MAX_WIRE_ENTRIES, describe_entry
from src.core.timers.reader import UNKNOWN_PROCESS, iso
from src.core.attention.fresh_observation import fresh_observation, watcher_of
from src.core.timers.session import process_fact_for, read_session_timers
from src.models.timers import BackgroundTasks, ParkedEntry, SessionTimers

logger = structlog.get_logger()
router = APIRouter()


def _observation(session_manager: Any, row_id: str) -> Optional[Any]:
    return fresh_observation(watcher_of(session_manager), row_id, datetime.now(timezone.utc))


def _parked_entries(observation: Optional[Any]) -> list[ParkedEntry]:
    parked = getattr(getattr(observation, "evidence", None), "parked_work", None)
    entries = list(getattr(parked, "entries", ()) or ())[:MAX_WIRE_ENTRIES]
    if not entries:
        return []
    now = datetime.now(timezone.utc)
    return [
        ParkedEntry(
            task_id=entry.task_id,
            kind="shell" if entry.kind == KIND_SHELL else "monitor",
            agent_id=entry.agent_id,
            live=entry.live,
            started_at=iso(entry.started_at) if entry.started_at else None,
            summary=describe_entry(entry, now=now),
        )
        for entry in entries
    ]


def background_from(observation: Optional[Any], family: Optional[str]) -> Optional[BackgroundTasks]:
    if family is not None and family != DEFAULT_FAMILY:
        return None
    parked = _parked_entries(observation)
    facts = getattr(getattr(observation, "evidence", None), "transcript", None)
    if facts is None or getattr(facts, "verdict", None) != FACTS_FOUND:
        return BackgroundTasks(
            open=None, detail="not measured: no fresh reading of the transcript",
            parked=parked,
        )
    return BackgroundTasks(
        open=facts.open_background_tasks,
        detail="background shell and monitor launches with no completion in the "
               "transcript's newest 256 KB; a floor, and counts only",
        parked=parked,
    )


@router.get(
    "/sessions/{session_id}/timers",
    response_model=SessionTimers,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_timers(request: Request, session_id: str) -> SessionTimers:
    """List the timers of a session's current conversation, with counts.

    Description: resolves the session (a created id or an
      ``adopted:<tmux-name>`` id), reads the conversation uuid off the
      stored row, measures the process from the watcher's observation,
      and reads the transcript on a worker thread.
    Inputs: request (Request). session_id (str).
    Output: SessionTimers.
    Raises: HTTPException 404 - no session carries this id.
    Example: GET /api/v1/sessions/ses_abc/timers
    """
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, "the timers read")
    info = await session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    tmux_name = info.tmux_session
    working_dir = info.session.working_dir if info.session is not None else None
    conversation_uuid = (
        session_manager.claude_uuid_for_tmux_name(tmux_name) if tmux_name else None
    )
    row_id = info.session.id if info.session is not None else session_id
    observation = _observation(session_manager, row_id)
    process = UNKNOWN_PROCESS
    if observation is not None:
        registry = getattr(observation.evidence, "registry", None)
        observed_uuid = observed_conversation_uuid(observation.evidence)
        conversation_uuid = observed_uuid or conversation_uuid
        process = process_fact_for(registry, conversation_uuid)
    subject = SessionSubject(agent_family=info.agent_family,
                             conversation_uuid=conversation_uuid, working_dir=working_dir)
    result = await asyncio.to_thread(read_session_timers, subject, process)
    result.background = background_from(observation, info.agent_family)
    logger.debug(
        "session_timers_read", session_id=session_id, state=result.state,
        live=result.counts.live if result.counts is not None else None,
        process=process.state,
    )
    return result
