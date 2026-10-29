
from __future__ import annotations

import asyncio
import sqlite3

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.core.api_keys.store import NAME_MAX, ApiKeyError, ApiKeyStoreError, get_store

logger = structlog.get_logger()


def _refuse_link(request: Request) -> None:
    if request.scope.get("via_link"):
        raise HTTPException(status_code=403, detail="not available over the link")


router = APIRouter(prefix="/api-keys", tags=["api-keys"], dependencies=[Depends(_refuse_link), Depends(require_auth)])


class CreateKeyBody(BaseModel):
    """``POST /api-keys``: the key's name (what script or computer holds it)."""

    name: str = Field(..., min_length=1, max_length=NAME_MAX)


def _store_failed(exc: Exception) -> HTTPException:
    logger.error("api_key_store_failed", error=type(exc).__name__)
    return HTTPException(status_code=500, detail="the api key file could not be read or written")


@router.post("", status_code=201)
async def create_api_key(body: CreateKeyBody) -> dict:
    """Create a key. Output: {key: row, secret} - the secret is shown here once and never stored.

    Raises: HTTPException 422 for a bad name or too many live keys, 500 when the file cannot be written.
    """
    try:
        row, secret = await asyncio.to_thread(get_store().create, body.name)
    except ApiKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (sqlite3.Error, ApiKeyStoreError) as exc:
        raise _store_failed(exc) from exc
    return {"key": row, "secret": secret}


@router.get("")
async def list_api_keys() -> dict:
    """Every key, newest first, revoked ones included; never a secret or a hash. Output: {keys}."""
    try:
        return {"keys": await asyncio.to_thread(get_store().list)}
    except (sqlite3.Error, ApiKeyStoreError) as exc:
        raise _store_failed(exc) from exc


@router.delete("/{key_id}")
async def revoke_api_key(key_id: str) -> dict:
    """Revoke a key; its next request gets 401. Output: {revoked: row}. Raises: HTTPException 404 unknown id, 500."""
    try:
        row = await asyncio.to_thread(get_store().revoke, key_id)
    except (sqlite3.Error, ApiKeyStoreError) as exc:
        raise _store_failed(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="no such api key")
    return {"revoked": row}
