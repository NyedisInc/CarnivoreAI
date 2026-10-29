
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth import require_auth
from src.core.deepsearch.query import SEARCH_QUERY_MAX_CHARS
from src.core.deepsearch import constants as K
from src.core.deepsearch import rules as rules_mod

logger = structlog.get_logger()

router = APIRouter(tags=["pipeline"], dependencies=[Depends(require_auth)])


def _state_dir():
    """The state directory. Separate function so tests can point it at a temp dir."""
    from src.config import settings as app_settings

    return app_settings.get_state_dir()


def body_search(state_dir, q: str, *, conversation_id: Optional[str] = None, project: Optional[str] = None,
                limit: int = K.SEARCH_LIMIT_DEFAULT) -> Dict[str, Any]:
    from src.core.deepsearch import search
    from src.core.deepsearch.cache import db as cache_db

    with closing(cache_db.reader(state_dir)) as conn:
        return search.search(conn, state_dir, q, conversation_id=conversation_id, project=project, limit=limit)


class FilterBody(BaseModel):
    """The new override document (merged over the shipped defaults)."""

    overrides: Dict[str, Any]


@router.get("/pipeline/search")
async def search_body(q: str = Query(..., min_length=1, max_length=SEARCH_QUERY_MAX_CHARS),
                      conversation_id: Optional[str] = Query(None, max_length=128),
                      project: Optional[str] = Query(None, max_length=200),
                      limit: int = Query(K.SEARCH_LIMIT_DEFAULT, ge=1, le=K.SEARCH_LIMIT_MAX)) -> Dict[str, Any]:
    """Search the filtered body of every indexed conversation. Output: see the module docstring."""
    import sqlite3

    from src.core.db import DatastoreUnreadableError

    try:
        return await asyncio.to_thread(body_search, _state_dir(), q, conversation_id=conversation_id,
                                       project=project, limit=limit)
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.error("search_index_unavailable", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail={"code": "search_index_unavailable", "detail": str(exc)})


def prompt_search(state_dir, q: str, *, project: Optional[str], limit: int, offset: int, per_group: int) -> Dict[str, Any]:
    from src.core.deepsearch import prompts
    from src.core.deepsearch.cache import db as cache_db

    with closing(cache_db.reader(state_dir)) as conn:
        return prompts.search_prompts(conn, state_dir, q, project=project, limit=limit, offset=offset,
                                      per_group=per_group)


@router.get("/pipeline/prompts/search")
async def search_prompts_route(q: str = Query(..., min_length=1, max_length=SEARCH_QUERY_MAX_CHARS),
                               project: Optional[str] = Query(None, max_length=200),
                               limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=100_000),
                               per_group: int = Query(3, ge=1, le=10)) -> Dict[str, Any]:
    """Search only the user's own prompts, grouped by conversation. Output: see the module docstring."""
    import sqlite3

    from src.core.db import DatastoreUnreadableError

    if not q.strip():
        raise HTTPException(status_code=422, detail={"code": "search_invalid", "detail": "q is empty"})
    try:
        return await asyncio.to_thread(prompt_search, _state_dir(), q.strip(), project=project, limit=limit,
                                       offset=offset, per_group=per_group)
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.error("prompt_search_unavailable", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail={"code": "search_index_unavailable", "detail": str(exc)})


@router.get("/pipeline/search-filter")
async def get_search_filter() -> Dict[str, Any]:
    """The filter rules: defaults, stored overrides, effective rules and version per family."""
    return rules_mod.describe(await asyncio.to_thread(rules_mod.read_overrides))


@router.put("/pipeline/search-filter")
async def put_search_filter(body: FilterBody) -> Dict[str, Any]:
    """Replace the stored overrides. Output: as the GET. 422 on invalid rules; 500 when config.json is missing."""
    try:
        stored = await asyncio.to_thread(rules_mod.write_overrides, body.overrides)
    except rules_mod.RulesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.error("search_filter_write_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="config.json could not be written") from exc
    return rules_mod.describe(stored)
