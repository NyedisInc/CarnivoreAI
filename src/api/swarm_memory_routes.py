
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth import require_auth
from src.api.swarm_routes import NEEDS_ON, NEEDS_PORT
from src.config import settings
from src.core import db
from src.core.swarm import body, memory, memory_edit
from src.models.swarm_memory import SwarmMemoryFile, SwarmMemoryFileRow, SwarmMemoryRestore, SwarmMemorySave

router = APIRouter(prefix="/swarm", tags=["swarm"], dependencies=[Depends(require_auth)])


def _fail(exc: Exception) -> NoReturn:
    if isinstance(exc, memory_edit.MemoryEditNotFound):
        raise HTTPException(status_code=404, detail={"code": "memory_not_found", "message": str(exc)}) from exc
    if isinstance(exc, (memory_edit.MemoryEditRefused, memory.SwarmFileError)):
        raise HTTPException(status_code=422, detail={"code": "memory_refused", "message": str(exc)}) from exc
    raise HTTPException(status_code=503, detail={"code": "datastore_unreadable", "message": "the memory could not be read"}) from exc


_ERRORS = (memory_edit.MemoryEditNotFound, memory_edit.MemoryEditRefused, memory.SwarmFileError,
           db.DatastoreUnreadableError, sqlite3.Error, OSError)


@router.get("/agents/{agent_id}/memory", response_model=List[SwarmMemoryFileRow], dependencies=NEEDS_PORT)
async def get_memory_files(agent_id: int) -> List[Dict[str, Any]]:
    """The agent's editable memory files. Raises: 404 ``memory_not_found``, 503."""
    try:
        return await body.run_db(lambda c: memory_edit.list_files(c, agent_id))
    except _ERRORS as exc:
        _fail(exc)


@router.get("/agents/{agent_id}/memory/file", response_model=SwarmMemoryFile, dependencies=NEEDS_PORT)
async def get_memory_file(agent_id: int, path: str = Query(..., max_length=64)) -> Dict[str, Any]:
    """One file's text and backups. Raises: 404, 422 (not MEMORY.md or a fact file), 503."""
    try:
        return await body.run_db(lambda c: memory_edit.read_file(c, settings.get_state_dir(), agent_id, path))
    except _ERRORS as exc:
        _fail(exc)


@router.put("/agents/{agent_id}/memory/file", response_model=SwarmMemoryFile, dependencies=NEEDS_ON)
async def put_memory_file(agent_id: int, payload: SwarmMemorySave) -> Dict[str, Any]:
    """Save one file after backing up its current text. Raises: 404, 422 (a secret, an empty fact, a bad path), 503."""
    try:
        return await body.run_db(
            lambda c: memory_edit.save_file(c, settings.get_state_dir(), agent_id, payload.path, payload.text))
    except _ERRORS as exc:
        _fail(exc)


@router.post("/agents/{agent_id}/memory/restore", response_model=SwarmMemoryFile, dependencies=NEEDS_ON)
async def restore_memory_file(agent_id: int, payload: SwarmMemoryRestore) -> Dict[str, Any]:
    """Put a backup back; the replaced text is backed up first. Raises: 404 (nothing to undo, no such backup), 422, 503."""
    try:
        return await body.run_db(lambda c: memory_edit.restore_backup(
            c, settings.get_state_dir(), agent_id, payload.path, payload.backup_id))
    except _ERRORS as exc:
        _fail(exc)
