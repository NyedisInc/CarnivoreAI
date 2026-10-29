
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.cplugs.save import folder_routes, import_routes, settings_routes, start
from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import points as vault_points
from src.cplugs.save.vault import restore
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.manifest import ManifestError, SoleCopyError
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import CplugContext, cplug_context, cplug_router, transcript_files as tf

logger = structlog.get_logger()
router = cplug_router("save")
settings_routes.add_to(router)
folder_routes.add_to(router)
import_routes.add_to(router)


class PointList(BaseModel):
    """Restore points, newest first. ``points`` items carry ``conversation_id``."""

    session_uuid: Optional[str] = None
    conversation_id: Optional[str] = None
    points: List[Dict[str, Any]]


class PinBody(BaseModel):
    """Pin or unpin a point."""

    pinned: bool


class PinResult(BaseModel):
    """The point's pin state after the call."""

    id: str
    pinned: bool


class DeleteResult(BaseModel):
    """Bytes freed by a delete."""

    id: str
    freed_bytes: int


class RestoreBody(BaseModel):
    """How to restore: the exact transcript, then (granted) a session resuming it."""

    agent_type: Optional[str] = Field(None, description="wrapper to start the resumed session with; defaults to the point's")


class SessionStart(BaseModel):
    """What the start step did after the restore."""

    status: str = Field(description="started | refused | not_attempted")
    code: str = Field("", description="grant_needed when the owner has not granted the start permissions")
    session_uuid: Optional[str] = None
    session_name: Optional[str] = None
    session_id: Optional[str] = None
    detail: str = ""


class RestoreResponse(BaseModel):
    """Result of a restore: the transcript part, then the start step."""

    transcript_status: str = Field(description="written | already_present")
    transcript_path: str = ""
    subagents_written: int = 0
    subagents_skipped: int = 0
    conversation_id: str
    session: SessionStart


def _vault() -> Vault:
    try:
        return RUNTIME.vault()
    except VaultUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})


def _session_conversations(vault: Vault, session_uuid: str) -> List[str]:
    return vault_points.SESSIONS.conversations(vault, session_uuid)


def _points_for(vault: Vault, conversation_ids: List[str]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for conv in conversation_ids:
        merged.extend(vault_points.list_points(vault, conv))
    merged.sort(key=lambda p: p.get("created_epoch") or 0, reverse=True)
    return merged


def _conversation_for_point(session_uuid: str, point_id: str) -> str:
    vault = _vault()
    owners = [c for c in _session_conversations(vault, session_uuid) if point_id in vault.manifests.point_ids(c)]
    if not owners:
        raise HTTPException(status_code=404, detail=f"no restore point {point_id} for this session")
    if len(owners) > 1:
        raise HTTPException(status_code=409, detail="that point id exists in several conversations of this session; "
                            "use the /conversations/ route")
    return owners[0]


def _guard(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except ManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except vault_points.PinnedError as exc:
        raise HTTPException(status_code=409, detail={"code": "pinned", "detail": str(exc)})
    except SoleCopyError as exc:
        raise HTTPException(status_code=409, detail={"code": "sole_copy", "detail": str(exc)})
    except vault_points.UnknownPoint as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sessions/{session_uuid}/points", response_model=PointList)
async def points_for_session(session_uuid: str) -> PointList:
    """Every restore point recorded for this session row, newest first."""
    def read() -> PointList:
        vault = _vault()
        convs = _session_conversations(vault, session_uuid)
        return PointList(session_uuid=session_uuid, conversation_id=convs[0] if len(convs) == 1 else None,
                         points=_points_for(vault, convs))
    return await run_in_threadpool(read)


@router.get("/conversations/{conversation_id}/points", response_model=PointList)
async def points_for_conversation(conversation_id: str) -> PointList:
    """Every restore point of one conversation, newest first. 400 for an id that is not a safe path segment."""
    return await run_in_threadpool(_guard, lambda: PointList(conversation_id=conversation_id,
                                                             points=_points_for(_vault(), [conversation_id])))


async def _pin(conversation_id: str, point_id: str, pinned: bool) -> PinResult:
    await run_in_threadpool(_guard, lambda: vault_points.set_pinned(_vault(), conversation_id, point_id, pinned))
    return PinResult(id=point_id, pinned=pinned)


async def _delete(conversation_id: str, point_id: str) -> DeleteResult:
    freed = await run_in_threadpool(_guard, lambda: vault_points.delete_point(_vault(), conversation_id, point_id))
    return DeleteResult(id=point_id, freed_bytes=freed)


async def _restore(ctx: CplugContext, conversation_id: str, point_id: str, body: RestoreBody) -> RestoreResponse:
    def run() -> vault_points.PointRestore:
        try:
            return vault_points.restore_point(_vault(), conversation_id, point_id, {"claude": Path(tf.projects_dir()).parent, "claude/projects": Path(tf.projects_dir())})
        except restore.RestoreConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "transcript_exists", "detail": str(exc)})
        except restore.RestoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    result = await run_in_threadpool(_guard, run)
    logger.info("save_point_restored", conversation_id=conversation_id, point_id=point_id, status=result.status)
    session = await start.start_after_restore(ctx, result.session_uuid, body.agent_type or result.wrapper)
    return RestoreResponse(transcript_status=result.status, transcript_path=str(result.transcript_path),
                           subagents_written=result.subagents_written, subagents_skipped=result.subagents_skipped,
                           conversation_id=result.conversation_id, session=SessionStart(**session))


@router.post("/conversations/{conversation_id}/points/{point_id}/pin", response_model=PinResult)
async def pin_by_conversation(conversation_id: str, point_id: str, body: PinBody) -> PinResult:
    """Pin (never ages out) or unpin a point."""
    return await _pin(conversation_id, point_id, body.pinned)


@router.delete("/conversations/{conversation_id}/points/{point_id}", response_model=DeleteResult)
async def delete_by_conversation(conversation_id: str, point_id: str) -> DeleteResult:
    """Delete a point (409 when pinned or the conversation's only point)."""
    return await _delete(conversation_id, point_id)


@router.post("/conversations/{conversation_id}/points/{point_id}/restore", response_model=RestoreResponse)
async def restore_by_conversation(conversation_id: str, point_id: str, body: RestoreBody,
                                  ctx: CplugContext = Depends(cplug_context("save"))) -> RestoreResponse:
    """Restore a point (see :class:`RestoreBody`)."""
    return await _restore(ctx, conversation_id, point_id, body)


@router.post("/sessions/{session_uuid}/points/{point_id}/pin", response_model=PinResult)
async def pin_by_session(session_uuid: str, point_id: str, body: PinBody) -> PinResult:
    """Pin or unpin a point of this session row."""
    return await _pin(await run_in_threadpool(_conversation_for_point, session_uuid, point_id), point_id, body.pinned)


@router.delete("/sessions/{session_uuid}/points/{point_id}", response_model=DeleteResult)
async def delete_by_session(session_uuid: str, point_id: str) -> DeleteResult:
    """Delete a point of this session row (409 when pinned or the conversation's only point)."""
    return await _delete(await run_in_threadpool(_conversation_for_point, session_uuid, point_id), point_id)


@router.post("/sessions/{session_uuid}/points/{point_id}/restore", response_model=RestoreResponse)
async def restore_by_session(session_uuid: str, point_id: str, body: RestoreBody,
                             ctx: CplugContext = Depends(cplug_context("save"))) -> RestoreResponse:
    """Restore a point of this session row."""
    conv = await run_in_threadpool(_conversation_for_point, session_uuid, point_id)
    return await _restore(ctx, conv, point_id, body)
