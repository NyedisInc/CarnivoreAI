
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api import pack_copy_sync, projects_service
from src.api.peer_auth import Principal, require_peer
from src.config import settings
from src.core.db import transaction
from src.core.pack.identity import home, replicas
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.migrate import code
from src.core.pack.transport import blobs, bundles

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack", tags=["federation"])
_require_replica = require_peer("replica", also=("migrate",))
pack_capabilities.register("pack.transport")


def inbox() -> blobs.Inbox:
    return blobs.Inbox(Path(settings.get_state_dir()) / "pack" / "inbox")


def _peer_only(principal: Principal) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer sends a blob"})
    return principal.grant.peer_install_id


def _refuse(exc: blobs.BlobError) -> JSONResponse:
    body: Dict[str, Any] = {"detail": {"code": exc.code}}
    if exc.received is not None:
        body["received"] = exc.received
    return JSONResponse(body, status_code=exc.status)


class SealBody(BaseModel):
    """The whole-blob check sent after the last chunk."""

    model_config = ConfigDict(extra="forbid")

    size: int = Field(ge=0, le=blobs.MAX_BLOB_BYTES)
    sha256: str = Field(min_length=64, max_length=64)
    kind: str = Field(max_length=32)


class ApplyBody(BaseModel):
    """A sealed bundle blob and the project (by uid) it belongs to."""

    model_config = ConfigDict(extra="forbid")

    blob_id: str = Field(max_length=64)
    project_uid: str = Field(min_length=8, max_length=64)
    branch: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$")
    remote: Optional[str] = Field(default=None, max_length=500)


def _note(blob_id: str, peer: str, kind: Any, size: int, state: str, **extra: Any) -> None:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        with transaction(conn):
            blobs.ledger_note(conn, blob_id, peer, "in", kind, size, state, **extra)


@router.put("/blobs/{blob_id}")
async def put_chunk(blob_id: str, request: Request, offset: int = Query(ge=0), principal: Principal = Depends(_require_replica)) -> Any:
    """Append one chunk at exactly the current size (the sender resumes from ``received`` on a 409). Output: {received}."""
    peer = _peer_only(principal)
    data = await request.body()
    try:
        size = await run_in_threadpool(inbox().put, blob_id, offset, data, request.headers.get("x-chunk-sha256", ""), peer)
        if offset == 0:
            await run_in_threadpool(_note, blob_id, peer, None, size, "receiving")
    except blobs.BlobError as exc:
        return _refuse(exc)
    return {"received": size}


@router.post("/blobs/{blob_id}/seal")
async def seal_blob(blob_id: str, body: SealBody, principal: Principal = Depends(_require_replica)) -> Any:
    """Verify the whole blob (size and sha256) and make it readable. Output: {sealed: true, size}."""
    peer = _peer_only(principal)
    try:
        path = await run_in_threadpool(inbox().seal, blob_id, body.size, body.sha256, body.kind)
    except blobs.BlobError as exc:
        return _refuse(exc)
    await run_in_threadpool(lambda: _note(blob_id, peer, body.kind, body.size, "sealed", sha256=body.sha256, path=str(path)))
    return {"sealed": True, "size": body.size}


@router.get("/blobs/{blob_id}")
async def blob_status(blob_id: str, principal: Principal = Depends(_require_replica)) -> Any:
    """How much of a blob is here and whether it is sealed (resume after a link loss). Output: {received, sealed}."""
    _peer_only(principal)
    try:
        return await run_in_threadpool(inbox().status, blob_id)
    except blobs.BlobError as exc:
        return _refuse(exc)


@router.post("/bundle/apply")
async def apply_bundle(body: ApplyBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Fetch a sealed bundle into ``refs/carnivore/<sender>/...`` of the project's checkout here, then delete the blob.

    Inputs: body (ApplyBody). Output: {refs} (how many refs the sender's namespace holds now).
    Raises: HTTPException 403 not a peer or ``not_a_counterpart``, 404 ``unknown_project`` / ``unknown_blob``, 409
      ``project_moved_away`` / ``bundle_unverified`` / ``bundle_apply_failed``.
    """
    sender = _peer_only(principal)
    applied: Dict[str, Any] = {}

    def run() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            row = conn.execute("SELECT * FROM projects WHERE uid = ?", (body.project_uid,)).fetchone()
            if row is None:
                raise HTTPException(404, {"code": "unknown_project", "detail": "no project with that uid here"})
            project = dict(row)
            applied.update(project)
            if project["pack_state"] == home.MOVED_AWAY:
                raise home.ProjectMovedAway(project["display_name"], home.machine_label(conn, project.get("moved_to_install_id")), project["root"])
            counterparts = {r["install_id"] for r in replicas.list_replicas(conn, project["uid"])} if project["pack_state"] == home.HOME \
                else {project.get("home_install_id")}
            if sender not in counterparts:
                raise HTTPException(403, {"code": "not_a_counterpart", "detail": "that computer is neither this project's home nor its replica"})
        try:
            path = inbox().sealed_path(body.blob_id, peer=sender)
        except blobs.BlobError as exc:
            raise HTTPException(exc.status, {"code": exc.code}) from exc
        try:
            refs = bundles.apply_bundle(project["root"], str(path), sender, air_gap=bool(project.get("air_gap")))
        except bundles.BundleError as exc:
            raise HTTPException(409, {"code": exc.code, "detail": exc.detail}) from exc
        inbox().remove(body.blob_id)
        if project["pack_state"] == home.REPLICA and body.branch:
            try:
                code.checkout_replica(project["root"], sender, body.branch, body.remote, air_gap=bool(project.get("air_gap")))
            except code.CodeError as exc:
                raise HTTPException(409, {"code": exc.code, "detail": exc.detail}) from exc
        return {"refs": refs}

    logger.info("pack_bundle_apply", project_uid=body.project_uid, sender=sender)
    answer = await run_in_threadpool(run)
    await pack_copy_sync.after_apply(request.app.state, applied, sender)
    return answer
