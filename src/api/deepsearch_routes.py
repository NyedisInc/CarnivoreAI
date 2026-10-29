
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.core.deepsearch import index_scope, reader, scope_settings, service
from src.core.deepsearch.reader import ContextNotFound, ConversationsUnavailable, InvalidSearch

logger = structlog.get_logger()

router = APIRouter(prefix="/deepsearch", tags=["deepsearch"], dependencies=[Depends(require_auth)])


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": "deepsearch_unavailable", "detail": str(exc)[:300]})


@router.get("/search")
async def search(q: str = Query(..., min_length=1, max_length=service.MAX_QUERY_CHARS),
                 kinds: Optional[str] = Query(None, max_length=100),
                 project: Optional[str] = Query(None, max_length=200),
                 conversation_id: Optional[str] = Query(None, max_length=128),
                 limit: int = Query(service.LIMIT_DEFAULT, ge=1, le=service.LIMIT_MAX),
                 offset: int = Query(0, ge=0, le=100_000),
                 per_group: int = Query(service.PER_GROUP_DEFAULT, ge=1, le=service.PER_GROUP_MAX),
                 scope: str = Query(service.SCOPE_ALL, pattern="^(local|peers|all)$")) -> Dict[str, Any]:
    """Search conversation text, grouped by conversation. Output: see the module docstring."""
    if not q.strip():
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": "q is empty"})
    try:
        return await service.search(reader.default_index(), q.strip(), kinds=service.parse_kinds(kinds), project=project,
                                    conversation_id=conversation_id, limit=limit, offset=offset, per_group=per_group,
                                    scope=scope)
    except InvalidSearch as exc:
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": str(exc)}) from exc
    except ConversationsUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/context")
async def context(conversation_id: str = Query(..., min_length=1, max_length=128),
                  line: Optional[int] = Query(None, ge=0), at: Optional[str] = Query(None, min_length=1, max_length=64),
                  before_line: Optional[int] = Query(None, ge=0), after_line: Optional[int] = Query(None, ge=0),
                  file_kind: str = Query("conversation", pattern="^(conversation|subagent)$"),
                  before: int = Query(service.CONTEXT_DEFAULT, ge=1, le=service.CONTEXT_MAX),
                  after: int = Query(service.CONTEXT_DEFAULT, ge=1, le=service.CONTEXT_MAX),
                  host_key: Optional[str] = Query(None, max_length=128)) -> Dict[str, Any]:
    """A window of one conversation around an anchor. Output: see the module docstring."""
    if sum(x is not None for x in (line, at, before_line, after_line)) != 1:
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": "name exactly one anchor"})
    try:
        return await service.context(reader.default_index(), conversation_id, file_kind=file_kind, line=line, at=at, before_line=before_line,
                                     after_line=after_line, before=before, after=after, host_key=host_key)
    except ContextNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "context_not_found", "detail": str(exc)}) from exc
    except ConversationsUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/suggest")
async def suggest(q: str = Query(..., max_length=service.SUGGEST_QUERY_MAX),
                  limit: int = Query(service.SUGGEST_LIMIT_DEFAULT, ge=1, le=service.SUGGEST_LIMIT_MAX)) -> Dict[str, Any]:
    """Autocomplete terms for a typed prefix. Output: see the module docstring."""
    try:
        return await service.suggest(reader.default_index(), q, limit=limit)
    except InvalidSearch as exc:
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": str(exc)}) from exc
    except ConversationsUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/status")
async def status() -> Dict[str, Any]:
    """The ingest state, newest indexed time and coverage. Output: see the module docstring."""
    try:
        return await reader.default_index().status()
    except ConversationsUnavailable as exc:
        raise _unavailable(exc) from exc


class ScopeSetting(BaseModel):

    model_config = ConfigDict(extra="forbid")

    indexScope: Literal["human", "human+subsessions", "all"]


def _scope_answer() -> Dict[str, Any]:
    return {"indexScope": index_scope.current(), "scopes": list(index_scope.SCOPES)}


@router.get("/settings")
async def get_settings() -> Dict[str, Any]:
    """The index scope in force. Output: {indexScope, scopes}."""
    return _scope_answer()


@router.put("/settings")
async def put_settings(body: ScopeSetting, request: Request) -> Dict[str, Any]:
    """Store the index scope and have the pipeline act on it now. Output: {indexScope, scopes}.

    Raises: HTTPException 422 (a value that is not a scope word, by the model); 500 ``deepsearch_settings_unwritable``.
    """
    try:
        result = scope_settings.save(request.app.state.ui_preferences_store, body.indexScope)
    except (FileNotFoundError, OSError) as exc:
        logger.error("deepsearch_settings_unwritable", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail={"code": "deepsearch_settings_unwritable", "detail": "config.json cannot be written"}) from exc
    if result.status not in ("committed", "unchanged"):
        raise HTTPException(status_code=422, detail={"code": "deepsearch_invalid", "detail": result.detail or result.status})
    return {"indexScope": body.indexScope, "scopes": list(index_scope.SCOPES)}
