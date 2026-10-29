
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.attention.codex_gather import DEFAULT_CODEX_HOME, rollout_path_in_sessions
from src.core.attention.evidence import FAMILY_CODEX
from src.core.session_token_usage import claude_reader
from src.core.session_transcript_presence import CONVERSATION_PRESENT
from src.core.skill_fires.tally import SkillTallyCache, STATE_MEASURED, default_store
from src.models.sessions import SessionSkillFires, SkillFireOut

router = APIRouter()

MAX_RECENT = 50


def _transcript_for(family: Optional[str], uuid: Optional[str], working_dir: Optional[str]) -> Optional[str]:
    if not uuid:
        return None
    if family == FAMILY_CODEX:
        return rollout_path_in_sessions(DEFAULT_CODEX_HOME, uuid)
    location = claude_reader.locate_transcript(uuid, working_dir=working_dir)
    return str(location.path) if location.outcome == CONVERSATION_PRESENT else None


def read_skill_fires(family: Optional[str], uuid: Optional[str], working_dir: Optional[str],
                     limit: int) -> SessionSkillFires:
    path = _transcript_for(family, uuid, working_dir)
    cache = SkillTallyCache()
    tally = cache.tally(family, path)
    if tally.state != STATE_MEASURED or path is None:
        return SessionSkillFires(state=tally.state)
    rows = default_store().recent(os.path.realpath(path), limit)
    return SessionSkillFires(state=tally.state, fired=tally.fired, recent=[
        SkillFireOut(skill=r.skill, at=r.fired_at, source=r.source,
                     harness=r.harness, profile=r.profile) for r in rows])


async def locate_conversation(request: Request, session_id: str, what: str) -> Tuple[Any, Optional[str], Optional[str]]:
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, what)
    info = await session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    tmux_name = info.tmux_session
    working_dir = info.session.working_dir if info.session is not None else None
    uuid: Optional[str] = session_manager._claude_uuid_for_tmux_name(tmux_name) if tmux_name else None
    row_id = info.session.id if info.session is not None else session_id
    watcher = getattr(session_manager, "_attention_watcher", None)
    observation = watcher.observation_for(row_id, now=datetime.now(timezone.utc)) if watcher else None
    if observation is not None and not observation.stale:
        uuid = (getattr(observation.evidence, "identity", None) or (None,) * 5)[4] or uuid
    return info, uuid, working_dir


@router.get(
    "/sessions/{session_id}/skill-fires",
    response_model=SessionSkillFires,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_skill_fires(
    request: Request, session_id: str, limit: int = Query(20, ge=1, le=MAX_RECENT),
) -> SessionSkillFires:
    """List the newest skill fires of a session's current conversation.

    Inputs: request (Request). session_id (str). limit (int, 1..50).
    Output: SessionSkillFires.
    Raises: HTTPException 404 - no session carries this id.
    Example: GET /api/v1/sessions/ses_abc/skill-fires?limit=10
    """
    info, uuid, working_dir = await locate_conversation(request, session_id, "the skill fires read")
    return await asyncio.to_thread(read_skill_fires, info.agent_family, uuid, working_dir, limit)
