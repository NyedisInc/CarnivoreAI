
from __future__ import annotations

import asyncio
import sqlite3
from typing import Optional

import structlog
from fastapi import HTTPException, Request

from src.core.api_keys import fence
from src.core.api_keys.store import ApiKeyStoreError, get_store

logger = structlog.get_logger()

_BEARER = {"WWW-Authenticate": "Bearer"}


def _refused(status: int, reason: str) -> HTTPException:
    headers = _BEARER if status == 401 else None
    return HTTPException(status_code=status, detail={"reason": reason}, headers=headers)


async def admit(token: str, request: Optional[Request]) -> dict:
    try:
        row = await asyncio.to_thread(get_store().authenticate, token)
    except (sqlite3.Error, ApiKeyStoreError) as exc:
        logger.error("api_key_store_unavailable", error=type(exc).__name__)
        raise _refused(503, "api_key_store_unavailable") from exc
    if row is None:
        raise _refused(401, "api_key_invalid")
    if request is None:
        logger.warning("api_key_fenced", key_id=row["id"], family="no request context")
        raise _refused(403, fence.REASON)
    family = fence.fenced_family(request.scope.get("path"), request.url.path)
    if family is not None:
        logger.warning("api_key_fenced", key_id=row["id"], family=family, path=request.url.path)
        raise _refused(403, fence.REASON)
    request.state.auth_kind = "api_key"
    request.state.api_key_id = row["id"]
    return row
