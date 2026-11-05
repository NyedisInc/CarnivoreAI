
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.error_response import api_error
from src.core.bookmarks import rows
from src.core.bookmarks.errors import BookmarkError
from src.core.checkpoints import read
from src.core.checkpoints.store import Checkpoint, get_store
from src.models.session_git import GitFile, SessionGitDiff

router = APIRouter(tags=["turn-checkpoints"], dependencies=[Depends(require_auth)])


class CheckpointRow(BaseModel):
    """One snapshot in a session's list."""

    id: int
    prompt_uuid: str = Field(description="the turn's opening prompt record; a bookmark's entry_uuid")
    kind: str = Field(description="turn, or safety (taken before a revert)")
    created_at: float
    work_tree: str
    pinned: bool = Field(description="a bookmark points at this turn, so cleanup keeps it")
    left_out: List[str] = Field(description="files not captured: secret-looking or over 20 MB; a revert never changes them")


class CheckpointList(BaseModel):
    """A session's snapshots, newest first."""

    session_uuid: str
    checkpoints: List[CheckpointRow]


class CheckpointChanges(BaseModel):
    """What one turn changed, against the snapshot before it."""

    id: int
    files: List[GitFile]


class CheckpointRepoUsage(BaseModel):
    """One repository's checkpoint store."""

    work_tree: str
    checkpoints: int
    bytes: int
    disabled_reason: Optional[str] = Field(default=None, description="why capture is off here: timeout (over 15 s) or slow (over 5 s)")


class CheckpointUsage(BaseModel):
    """Disk use of every repository's checkpoint store."""

    repos: List[CheckpointRepoUsage]


def _uuid(session: str) -> str:
    try:
        return rows.read_row(session).session_uuid
    except BookmarkError as exc:
        raise api_error(exc.status, exc.code, exc) from exc


def _one(session: str, checkpoint_id: int) -> Checkpoint:
    for cp in get_store().for_session(_uuid(session)):
        if cp.id == checkpoint_id:
            return cp
    raise api_error(404, "checkpoint_not_found")


@router.get("/sessions/{session_uuid}/checkpoints", response_model=CheckpointList)
async def list_checkpoints(session_uuid: str) -> CheckpointList:
    """A session's file snapshots, newest first (empty for a session that has none)."""

    def build() -> CheckpointList:
        store = get_store()
        uuid = _uuid(session_uuid)
        pins = store.pinned_prompts(uuid)
        listed = [CheckpointRow(id=c.id, prompt_uuid=c.prompt_uuid, kind=c.kind, created_at=c.created_at,
                              work_tree=c.work_tree, pinned=c.prompt_uuid in pins, left_out=c.left_out)
                for c in store.for_session(uuid)]
        return CheckpointList(session_uuid=uuid, checkpoints=listed)

    return await run_in_threadpool(build)


@router.get("/sessions/{session_uuid}/checkpoints/{checkpoint_id}/changes", response_model=CheckpointChanges)
async def checkpoint_changes(session_uuid: str, checkpoint_id: int) -> CheckpointChanges:
    """The files one turn changed. 404 for an unknown snapshot, 503 when git could not answer."""

    def build() -> CheckpointChanges:
        cp = _one(session_uuid, checkpoint_id)
        files = read.changes(get_store(), cp)
        if files is None:
            raise api_error(503, "checkpoint_unreadable")
        return CheckpointChanges(id=cp.id, files=files)

    return await run_in_threadpool(build)


@router.get("/sessions/{session_uuid}/checkpoints/{checkpoint_id}/diff", response_model=SessionGitDiff)
async def checkpoint_diff(session_uuid: str, checkpoint_id: int, path: str = Query(..., min_length=1)) -> SessionGitDiff:
    """One changed file's diff inside a turn. The path must be one of that turn's changes (404 otherwise)."""

    def build() -> SessionGitDiff:
        store = get_store()
        cp = _one(session_uuid, checkpoint_id)
        files = read.changes(store, cp) or []
        entry = next((f for f in files if f.path == path), None)
        if entry is None:
            raise api_error(404, "checkpoint_file_unchanged")
        return read.file_diff(store, cp, entry)

    return await run_in_threadpool(build)


@router.get("/checkpoints/usage", response_model=CheckpointUsage)
async def checkpoint_usage() -> CheckpointUsage:
    """Checkpoint count and disk use per repository, and why capture is off for a repo, for Settings."""
    found = await run_in_threadpool(lambda: read.usage(get_store()))
    return CheckpointUsage(repos=[CheckpointRepoUsage(**r) for r in found])
