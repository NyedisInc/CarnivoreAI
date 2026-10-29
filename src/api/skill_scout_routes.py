
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.catalog_routes import refuse_empty
from src.core.swarm import delivery as swarm_delivery
from src.api.session_skill_fires_routes import _transcript_for, locate_conversation
from src.core.attention.evidence import FAMILY_CLAUDE
from src.core.skill_fires.tally import SkillTallyCache, default_store
from src.core.skill_scout import digest as digest_mod
from src.core.skill_scout.prompt import MARKER, build_prompt
from src.core.skill_scout.reply import read_reply
from src.models.skill_scout import ScoutReply, ScoutRequested, ScoutSuggestion

router = APIRouter()

WHAT = "the skill scout"

IN_FLIGHT_SECONDS: float = 600.0
_IN_FLIGHT: Dict[str, float] = {}
REPLY_GRACE_SECONDS: float = 5.0


def _in_flight(key: str) -> bool:
    since = _IN_FLIGHT.get(key)
    if since is None:
        return False
    if time.monotonic() - since >= IN_FLIGHT_SECONDS:
        _IN_FLIGHT.pop(key, None)
        return False
    return True


async def _verified_skills(request: Request) -> Dict[str, Any]:
    snapshot = await request.app.state.services.catalog.index_cache.get()
    refuse_empty(snapshot)
    if snapshot.verified is None:
        raise HTTPException(status_code=409, detail={
            "code": "index_unavailable", "message": "the catalog index has not been verified yet"})
    return {i.id: i for i in snapshot.verified.items if i.kind == "skill" and i.deprecated is None}


def _fired_names(family: Optional[str], path: str) -> List[str]:
    SkillTallyCache().tally(family, path)
    return [r.skill for r in default_store().recent(os.path.realpath(path), 50)]


def _digest_for(family: Optional[str], path: Optional[str]) -> digest_mod.Digest:
    fired = _fired_names(family, path) if path else []
    return digest_mod.build_digest(path, fired, MARKER)


def _installed_ids(request: Request) -> set:
    with request.app.state.services.catalog.ledger() as ledger:
        return {row.item_id for row in ledger.list()}


async def _conversation(request: Request, session_id: str) -> Tuple[Any, Optional[str]]:
    info, uuid, working_dir = await locate_conversation(request, session_id, WHAT)
    if info.agent_family != FAMILY_CLAUDE:
        raise HTTPException(status_code=409, detail={
            "code": "scout_unsupported", "message": "the scout reads a Claude transcript; this session is not one"})
    path = await asyncio.to_thread(_transcript_for, info.agent_family, uuid, working_dir)
    return info, path


@router.post(
    "/sessions/{session_id}/skills/scout",
    response_model=ScoutRequested,
    dependencies=[Depends(require_peer_sessions)],
)
async def post_skill_scout(request: Request, session_id: str) -> ScoutRequested:
    """Paste the scout prompt into the session's agent and submit it.

    Inputs: request (Request); session_id (str) - either id shape.
    Output: ScoutRequested.
    Raises: 404 unknown session; 409 with a ``code`` when the paste gates
      refuse (question or dialog open, dead pane, not an agent), the index
      is not held, or ``scout_in_flight`` (the last request has no reply
      and is under ten minutes old); nothing is pasted on any refusal.
    Example: POST /api/v1/sessions/ses_1/skills/scout
    """
    info, path = await _conversation(request, session_id)
    items = await _verified_skills(request)
    installed = _installed_ids(request)
    listed = [i for i in items.values() if i.id not in installed]
    if not listed:
        raise HTTPException(status_code=409, detail={
            "code": "nothing_to_scout", "message": "the verified index has no skill you have not installed"})
    key = info.tmux_session or session_id
    if _in_flight(key):
        raise HTTPException(status_code=409, detail={
            "code": "scout_in_flight", "message": "the last scout request has no reply yet"})
    digest = await asyncio.to_thread(_digest_for, info.agent_family, path)
    prompt = build_prompt(listed, digest)
    _IN_FLIGHT[key] = time.monotonic()
    try:
        result = await swarm_delivery.paste_as_data(request, session_id, prompt, f"skill_scout:{session_id}")
    except BaseException:
        _IN_FLIGHT.pop(key, None)
        raise
    return ScoutRequested(pasted_bytes=result.pasted_bytes, items_listed=min(len(listed), 80))


@router.get(
    "/sessions/{session_id}/skills/scout",
    response_model=ScoutReply,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_skill_scout(request: Request, session_id: str) -> ScoutReply:
    """The suggestions the agent answered the latest scout request with.

    Inputs: request (Request); session_id (str).
    Output: ScoutReply (state none, waiting, ready, not_measured).
    Example: GET /api/v1/sessions/ses_1/skills/scout
    """
    try:
        info, path = await _conversation(request, session_id)
    except HTTPException as exc:
        if exc.status_code == 409 and isinstance(exc.detail, dict) and exc.detail.get("code") == "scout_unsupported":
            return ScoutReply(state="unsupported", detail=exc.detail["message"])
        raise
    if path is None:
        return ScoutReply(state="not_measured")
    items = await _verified_skills(request)
    records = await asyncio.to_thread(digest_mod.read_tail, path)
    state, found = read_reply(records, set(items))
    key = info.tmux_session or session_id
    if state == "ready" and time.monotonic() - _IN_FLIGHT.get(key, 0.0) > REPLY_GRACE_SECONDS:
        _IN_FLIGHT.pop(key, None)
    installed = _installed_ids(request)
    return ScoutReply(state=state, suggestions=[
        ScoutSuggestion(item_id=s.item_id, name=items[s.item_id].name, reason=s.reason)
        for s in found if s.item_id not in installed])
