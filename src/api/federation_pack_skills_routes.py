
from __future__ import annotations

import collections
import os
import secrets
import shutil
import threading
import time
from functools import partial
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, conlist, constr

from src.api.peer_auth import Principal, require_peer
from src.config import settings
from src.core.computers import direction
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.skills import apply as skills_apply
from src.core.pack.skills import receiver, rules, take_export, warez_receiver
from src.core.pack.skills.bundle import BundleError, read_bundle
from src.core.pack.skills.receiver import ReceiverError, ReceiverState
from src.core.pack.skills.scan import scan_root
from src.core.pack.skills.targets import SkillRoot, receiver_roots
from src.core.pack.transport import blobs
from src.core.provider_ledger import accounts_store
from src.core.skills.records import SIDECAR_NAME

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack/skills", tags=["federation"])
_require_skills = require_peer("skills")
pack_capabilities.register(pack_capabilities.CAP_SKILLS, pack_capabilities.CAP_SKILLS_REF, pack_capabilities.CAP_SKILLS_TAKE)

MAX_SKILLS_BLOB_BYTES = 102 * 1024 * 1024
RATE_PER_MINUTE = 12
MAX_OFFER_BODY = 64 * 1024
MAX_CHUNK_BODY = blobs.CHUNK_BYTES
_HITS: Dict[str, Deque[float]] = collections.defaultdict(collections.deque)
_HITS_LOCK = threading.Lock()
_STATES: Dict[str, ReceiverState] = {}
WORKER = skills_apply.ApplyWorker()


def state_dir() -> Path:
    return Path(settings.get_state_dir())


def receiver_state() -> ReceiverState:
    path = state_dir() / "pack" / "skills-state.json"
    return _STATES.setdefault(str(path), ReceiverState(path))


def skills_inbox() -> blobs.Inbox:
    return blobs.Inbox(state_dir() / "pack" / "skills-inbox", max_blob_bytes=MAX_SKILLS_BLOB_BYTES,
                       max_peer_bytes=MAX_SKILLS_BLOB_BYTES, max_total_bytes=MAX_SKILLS_BLOB_BYTES,
                       stale_seconds=3600.0, purge_sealed=True)


def roots_now() -> List[SkillRoot]:
    home = Path.home()
    try:
        accounts = accounts_store.list_accounts(Path(settings.auth_config_file).expanduser())
    except (OSError, ValueError):
        accounts = []
    dirs = [a.claude_config_dir for a in accounts if a.provider == "claude" and a.claude_config_dir]
    return receiver_roots(home, home / ".carnivore" / "accounts", dirs)


def held_alpha() -> Optional[str]:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    return wired.runtime.settings().master_install_id if wired is not None else None


def _limit(grant_id: str) -> None:
    now = time.monotonic()
    with _HITS_LOCK:
        hits = _HITS[grant_id]
        while hits and now - hits[0] > 60.0:
            hits.popleft()
        if len(hits) >= RATE_PER_MINUTE:
            raise HTTPException(429, {"code": "rate_limited", "detail": "too many skill sync calls this minute"})
        hits.append(now)


async def _alpha(principal: Principal = Depends(_require_skills)) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer sends skills"})
    peer = principal.grant.peer_install_id
    held = await run_in_threadpool(held_alpha)
    if held != peer:
        raise HTTPException(403, {"code": "not_alpha", "held_alpha": held, "detail": "only the Pack's alpha decides what syncs"})
    if direction.contained(peer):
        raise HTTPException(403, {"code": "alpha_one_way", "detail": "this computer holds that one as one way; nothing syncs from it"})
    return peer


async def _alpha_limited(principal: Principal = Depends(_require_skills), caller: str = Depends(_alpha)) -> str:
    _limit(principal.grant.grant_id)  # type: ignore[union-attr]
    return caller


def _fail(exc: ReceiverError) -> JSONResponse:
    return JSONResponse({"detail": {"code": exc.code}, **exc.extra}, status_code=exc.status)


def _refuse(exc: blobs.BlobError) -> JSONResponse:
    body: Dict[str, Any] = {"detail": {"code": exc.code}}
    if exc.received is not None:
        body["received"] = exc.received
    return JSONResponse(body, status_code=exc.status)


class ApplyBody(BaseModel):
    """Run the offered generation; ``blob_id`` is the sealed bundle (None when nothing is needed)."""

    model_config = ConfigDict(extra="forbid")

    gen: int = Field(ge=0)
    blob_id: Optional[str] = Field(default=None, max_length=64)
    blob_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)
    install: Optional[List[conlist(constr(max_length=64), min_length=2, max_length=2)]] = Field(default=None, max_length=400)


class SealBody(BaseModel):
    """The whole-blob check sent after the last chunk."""

    model_config = ConfigDict(extra="forbid")

    size: int = Field(ge=0, le=MAX_SKILLS_BLOB_BYTES)
    sha256: str = Field(min_length=64, max_length=64)
    kind: str = Field(max_length=32)


def _offer(doc: Any, caller: str) -> Dict[str, Any]:
    clean = receiver.validate_document(doc, caller)
    state = receiver_state()
    applied = state.applied_gen()
    if clean["gen"] < applied:
        raise ReceiverError("stale", 409, applied_gen=applied)
    receiver.forget(state, clean["unsynced"])
    cells = receiver.survey(clean, roots_now())
    state.pending = clean
    return {"need": receiver.need_list(cells), "need_refs": _need_refs(clean, state), "applied_gen": applied}


def _need_refs(clean: Dict[str, Any], state: ReceiverState) -> List[List[str]]:
    done = state.load().get("refs", {})
    services, _loop = refs_context()
    have = warez_receiver.installed_versions(services) if services is not None else None
    out = []
    for item_id, group in warez_receiver.parse(clean.get("warez", [])).items():
        rec = done.get(item_id, {})
        gone = have is not None and rec.get("outcome") == "in sync" and have.get(item_id) != rec.get("version")
        if group.bad or (not gone and rec.get("version") == group.ref.version and rec.get("digest") == group.ref.digest
                         and rec.get("outcome") in ("in sync", "conflict")):
            continue
        out += [[family, folder] for family, folder in sorted(group.folders.items())]
    return out


def refs_context() -> Any:
    from src.core.pack.skills import wiring

    sync = wiring.SYNC
    return (sync.services(), sync.loop) if sync is not None else (None, None)


def _cap_body(request: Request, limit: int) -> None:
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = limit + 1
    if declared > limit:
        raise HTTPException(413, {"code": "too_large", "detail": "request body is over the limit"})


@router.post("/offer")
async def offer(request: Request, caller: str = Depends(_alpha_limited)) -> Any:
    """Alpha's state document in, the pairs this computer needs bytes for out. Raises 403, 409 ``stale`` (with ``applied_gen``), 422 ``bad_document``."""
    try:
        _cap_body(request, MAX_OFFER_BODY)
        body = await request.json()
        return await run_in_threadpool(_offer, body, caller)
    except ValueError:
        return _fail(ReceiverError("bad_document"))
    except ReceiverError as exc:
        return _fail(exc)


def _make_job(doc: Dict[str, Any], caller: str, blob_id: Optional[str], install: Optional[List[List[str]]] = None) -> Any:
    state, inbox = receiver_state(), skills_inbox()

    def job() -> None:
        stage = state_dir() / "pack" / f"skills-stage-{secrets.token_hex(6)}"
        try:
            if held_alpha() != caller or doc["gen"] < state.applied_gen():
                logger.info("pack_skills_apply_dropped", gen=doc["gen"])
                return
            bundle = None
            if blob_id is not None:
                try:
                    bundle = read_bundle(inbox.sealed_path(blob_id, peer=caller), stage)
                except (BundleError, blobs.BlobError) as exc:
                    logger.warning("pack_skills_bundle_refused", code=getattr(exc, "code", "bad_bundle"))
                    return
            services, loop = refs_context()
            report = skills_apply.apply_document(doc, bundle, roots_now(), state, services=services)
            logger.info("pack_skills_applied", gen=doc["gen"], rows=len(report.rows), kept=len(report.kept))
            if doc.get("warez") and services is not None and loop is not None:
                ctx = warez_receiver.Context(state, roots_now(), services, loop, caller, doc["gen"],
                                             lambda: held_alpha() == caller and (state.load().get("doc") or {}).get("gen") == doc["gen"])
                warez_receiver.run(doc, ctx, install)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            if blob_id is not None:
                inbox.remove(blob_id)

    return job


@router.post("/apply", status_code=202)
async def apply(body: ApplyBody, caller: str = Depends(_alpha_limited)) -> Any:
    """Queue the offered generation. Output: ``{op_id}`` (the result shows in the next snapshot). Raises 409 ``no_offer`` / ``stale``, 403 ``blob_not_yours``, 404, 422."""
    state, inbox = receiver_state(), skills_inbox()
    pending = state.pending
    if pending is None or pending["gen"] != body.gen or pending["alpha"] != caller:
        return _fail(ReceiverError("no_offer", 409))
    applied = await run_in_threadpool(state.applied_gen)
    if body.gen < applied:
        return _fail(ReceiverError("stale", 409, applied_gen=applied))
    if body.blob_id is not None:
        try:
            path = await run_in_threadpool(partial(inbox.sealed_path, body.blob_id, peer=caller))
        except blobs.BlobError as exc:
            return _refuse(exc)
        if body.blob_sha256 is None or await run_in_threadpool(blobs.file_sha256, str(path)) != body.blob_sha256:
            await run_in_threadpool(inbox.remove, body.blob_id)
            return JSONResponse({"detail": {"code": "hash_mismatch"}}, status_code=422)
    blob_id = body.blob_id
    op_id = WORKER.submit(_make_job(pending, caller, blob_id, body.install), on_replaced=lambda: None)
    return {"op_id": op_id}


def _inventory() -> Dict[str, Any]:
    rows: List[List[Any]] = []
    for root in roots_now():
        if root.problem:
            continue
        found = scan_root(root.leaf, root.family)
        for name, skill in sorted(found.skills.items()):
            rows.append([root.family, name, root.group, skill.digest, os.path.lexists(root.leaf / name / SIDECAR_NAME)])
    state = receiver_state()
    services, _loop = refs_context()
    warez, conflicts = warez_receiver.inventory_rows(services, state.load()["applied"])
    return {"skills": rows[:rules.MAX_INVENTORY_ROWS], "truncated": len(rows) > rules.MAX_INVENTORY_ROWS, "applied_gen": state.applied_gen(),
            "warez": warez, "conflicts": conflicts}


@router.get("/inventory")
async def inventory(_caller: str = Depends(_alpha_limited)) -> Any:
    """What this computer holds, for alpha's dry run (owner-triggered on alpha, never on a timer)."""
    return await run_in_threadpool(_inventory)


def _drop_other_alphas(inbox: blobs.Inbox, alpha: str) -> None:
    if not inbox.directory.is_dir():
        return
    for path in inbox.directory.glob("*.part"):
        owner_id = inbox.owner(path.stem)
        if owner_id is not None and owner_id != alpha:
            inbox.remove(path.stem)
    for path in inbox.directory.glob("*.blob"):
        owner_id = inbox.owner(path.stem)
        if owner_id is not None and owner_id != alpha:
            inbox.remove(path.stem)


@router.put("/blobs/{blob_id}")
async def put_chunk(blob_id: str, request: Request, offset: int = Query(ge=0), caller: str = Depends(_alpha)) -> Any:
    """Append one chunk at exactly the current size (the sender resumes from ``received`` on a 409). Output: {received}."""
    _cap_body(request, MAX_CHUNK_BODY)
    data = await request.body()
    if len(data) > MAX_CHUNK_BODY:
        raise HTTPException(413, {"code": "too_large", "detail": "request body is over the limit"})
    inbox = skills_inbox()
    try:
        await run_in_threadpool(inbox.purge_stale)
        await run_in_threadpool(_drop_other_alphas, inbox, caller)
        size = await run_in_threadpool(inbox.put, blob_id, offset, data, request.headers.get("x-chunk-sha256", ""), caller)
    except blobs.BlobError as exc:
        return _refuse(exc)
    return {"received": size}


@router.post("/blobs/{blob_id}/seal")
async def seal_blob(blob_id: str, body: SealBody, caller: str = Depends(_alpha)) -> Any:
    """Verify the whole blob (size and sha256) and make it readable. Output: {sealed: true, size}."""
    try:
        await run_in_threadpool(skills_inbox().seal, blob_id, body.size, body.sha256, body.kind)
    except blobs.BlobError as exc:
        return _refuse(exc)
    return {"sealed": True, "size": body.size}


@router.get("/blobs/{blob_id}")
async def blob_status(blob_id: str, caller: str = Depends(_alpha)) -> Any:
    """How much of a blob is here and whether it is sealed (resume after a link loss). Status only, never the bytes."""
    try:
        return await run_in_threadpool(skills_inbox().status, blob_id)
    except blobs.BlobError as exc:
        return _refuse(exc)


def export_dir() -> Path:
    return state_dir() / "pack" / "skills-export"


class ExportBody(BaseModel):
    """The one skill alpha's owner wants this computer's copy of."""

    model_config = ConfigDict(extra="forbid")

    family: str = Field(max_length=16)
    name: str = Field(max_length=rules.MAX_NAME_BYTES)


def _export_fail(exc: take_export.ExportError) -> JSONResponse:
    return JSONResponse({"detail": {"code": exc.code, "detail": exc.detail}}, status_code=exc.status)


@router.post("/export")
async def export_skill(body: ExportBody, caller: str = Depends(_alpha_limited)) -> Any:
    """Bundle this computer's copy of one skill for the held alpha (a catalog install, a link or a skill the scan holds back is refused).

    Output: ``{blob_id, size, sha256, digest}``. Raises 404 ``not_found``, 413 ``too_large``, 422 ``bad_skill`` / ``catalog_skill`` / ``skill_is_link`` / ``skill_held``.
    """
    try:
        return await run_in_threadpool(take_export.make_export, roots_now(), body.family, body.name, export_dir())
    except take_export.ExportError as exc:
        return _export_fail(exc)


@router.get("/export/{blob_id}")
async def export_chunk(blob_id: str, offset: int = Query(ge=0), caller: str = Depends(_alpha)) -> Any:
    """One chunk of an export (at most 1 MiB of bytes, base64). Raises 400 ``bad_blob``, 404 ``not_found``."""
    try:
        return await run_in_threadpool(take_export.read_chunk, export_dir(), blob_id, offset)
    except take_export.ExportError as exc:
        return _export_fail(exc)


@router.post("/export/{blob_id}/done")
async def export_done(blob_id: str, caller: str = Depends(_alpha)) -> Any:
    """Alpha has the bytes: delete the export now (an hour later it is purged anyway)."""
    try:
        await run_in_threadpool(take_export.remove, export_dir(), blob_id)
    except take_export.ExportError as exc:
        return _export_fail(exc)
    return {"ok": True}
