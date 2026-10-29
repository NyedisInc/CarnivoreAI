
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api import peer_auth
from src.config import settings as app_settings
from src.core.federation import peer_deepsearch
from src.core.deepsearch.grouped import GROUP_LIMIT_DEFAULT, GROUP_LIMIT_MAX, PER_GROUP_DEFAULT, PER_GROUP_MAX
from src.core.deepsearch import constants as K
from src.core.deepsearch.cache import flip
from src.core.deepsearch.query import SEARCH_QUERY_MAX_CHARS
from src.core.deepsearch import peer_air_gap
from src.core.deepsearch.reader import ContextNotFound, ConversationIndex, ConversationsUnavailable, InvalidSearch

_inflight = 0

def _release(task: "asyncio.Future[Any]") -> None:
    global _inflight
    _inflight -= 1
    if not task.cancelled():
        task.exception()


router = APIRouter(prefix="/deepsearch", tags=["deepsearch"], dependencies=[Depends(peer_auth.require_peer_sessions)])


@router.get("/peer-search")
async def peer_search(q: str = Query(..., min_length=1, max_length=SEARCH_QUERY_MAX_CHARS),
                      kinds: Optional[str] = Query(None, max_length=100),
                      project: Optional[str] = Query(None, max_length=200),
                      conversation_id: Optional[str] = Query(None, max_length=128),
                      limit: int = Query(GROUP_LIMIT_DEFAULT, ge=1, le=GROUP_LIMIT_MAX),
                      per_group: int = Query(PER_GROUP_DEFAULT, ge=1, le=PER_GROUP_MAX)) -> Dict[str, Any]:
    global _inflight
    if not q.strip():
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": "q is empty"})
    state_dir = app_settings.get_state_dir()
    try:
        ready = await asyncio.to_thread(flip.state, state_dir) == K.CACHE_READY
    except OSError as exc:
        raise HTTPException(status_code=503, detail={"code": "deepsearch_unavailable", "detail": "the search index cannot be read"}) from exc
    terms = peer_deepsearch.peer_query(q)
    if not ready:
        return peer_deepsearch.not_ready_answer(q)
    if not terms:
        return peer_deepsearch.export({"query": q})
    if _inflight >= peer_deepsearch.PEER_MAX_INFLIGHT:
        raise HTTPException(status_code=429, detail={"code": "deepsearch_busy", "detail": "too many searches in flight"})
    _inflight += 1
    search = asyncio.ensure_future(ConversationIndex(state_dir).search(
        terms, kinds=[k.strip() for k in kinds.split(",") if k.strip()] if kinds else None, project=project, conversation_id=conversation_id,
        limit=limit, offset=0, per_group=per_group, peers=False, for_peer=True))
    search.add_done_callback(_release)
    try:
        answer = await asyncio.shield(search)
    except InvalidSearch as exc:
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": str(exc)}) from exc
    except ConversationsUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "deepsearch_unavailable", "detail": "the search index cannot be read"}) from exc
    except peer_air_gap.AirGapUnreadable as exc:
        raise HTTPException(status_code=503, detail={"code": "deepsearch_unavailable", "detail": "the project registry cannot be read"}) from exc
    return await asyncio.to_thread(peer_deepsearch.export, answer)


@router.get("/peer-context")
async def peer_context(conversation_id: str = Query(..., min_length=1, max_length=128),
                       line: Optional[int] = Query(None, ge=0), at: Optional[str] = Query(None, min_length=1, max_length=64),
                       before_line: Optional[int] = Query(None, ge=0), after_line: Optional[int] = Query(None, ge=0),
                       file_kind: str = Query("conversation", pattern="^(conversation|subagent)$"),
                       before: int = Query(20, ge=1, le=50), after: int = Query(20, ge=1, le=50)) -> Dict[str, Any]:
    if sum(x is not None for x in (line, at, before_line, after_line)) != 1:
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": "name exactly one anchor"})
    state_dir = app_settings.get_state_dir()
    try:
        window = await ConversationIndex(state_dir).context(conversation_id, file_kind=file_kind, line=line, at=at,
                                                            before_line=before_line, after_line=after_line, before=before,
                                                            after=after, for_peer=True)
    except ContextNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "context_not_found", "detail": "not found"}) from exc
    except ConversationsUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "deepsearch_unavailable", "detail": "the search index cannot be read"}) from exc
    return await asyncio.to_thread(peer_deepsearch.clean_context, window)
