
from __future__ import annotations

import asyncio
import threading
from contextlib import closing
from functools import partial
from pathlib import Path
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.federation_pack_skills_routes import _cap_body, _drop_other_alphas, _refuse, content_alpha
from src.api.peer_auth import Principal, open_db, read_install_id, require_peer
from src.config import settings
from src.core import resource_push, session_change_notice
from src.core.computers import direction
from src.core.db import get_meta, transaction
from src.core.db_models import META_INSTALL_ID
from src.core.pack.globalsync import apply as gs_apply, deps, panel as gs_panel, panel_merge, rules, wiring
from src.core.pack.globalsync.store import Status, clean_settings
from src.core.pack.globalsync.sender import CAP, PANEL_CHANGE_CAP
from src.core.pack.machines import capabilities as pack_capabilities, restrictions as restrictions_mod, runtime as machines_runtime
from src.core.pack.relay import approval
from src.core.pack.transport import blobs
from src.core.provider_ledger import accounts_store
from src.core.resource_push import topics

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack/global", tags=["federation"])
pack_capabilities.register(CAP)
pack_capabilities.register(gs_panel.CAP)
pack_capabilities.register(PANEL_CHANGE_CAP)
_require_global = require_peer("global-setup")
_require_machine = require_peer("machine")
_allowed = restrictions_mod.require_peer_allowed(restrictions_mod.ACTION_RECEIVE_GLOBAL_SETUP)
_APPLY_LOCK = threading.Lock()
MAX_BLOB_BYTES = rules.MAX_TOTAL_BYTES + 32 * 1024 * 1024
MAX_PANEL_BYTES = 4 * 1024 * 1024


def state_dir() -> Path:
    return Path(settings.get_state_dir())


def inbox() -> blobs.Inbox:
    return blobs.Inbox(state_dir() / "pack" / "global-inbox", max_blob_bytes=MAX_BLOB_BYTES, max_peer_bytes=MAX_BLOB_BYTES,
                       max_total_bytes=MAX_BLOB_BYTES, stale_seconds=3600.0, purge_sealed=True)


def local_accounts() -> List[Any]:
    try:
        return list(accounts_store.list_accounts(Path(settings.auth_config_file).expanduser()))
    except (OSError, ValueError):
        return []


def home_dir() -> Path:
    return Path.home()


async def _main(principal: Principal = Depends(_require_global), _ok: None = Depends(_allowed)) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer sends a global setup"})
    peer = principal.grant.peer_install_id
    held = await run_in_threadpool(content_alpha)
    if held != peer:
        raise HTTPException(403, {"code": "not_alpha", "held_alpha": held, "detail": "only the Pack's main computer sends a global setup"})
    if direction.contained(peer):
        raise HTTPException(403, {"code": "alpha_one_way", "detail": "this computer holds that one as one way; nothing syncs from it"})
    return peer


class SealBody(BaseModel):
    """The whole-blob check sent after the last chunk."""

    model_config = ConfigDict(extra="forbid")

    size: int = Field(ge=0, le=MAX_BLOB_BYTES)
    sha256: str = Field(min_length=64, max_length=64)
    kind: str = Field(max_length=32)


class ApplyBody(BaseModel):
    """Apply the sealed bundle; ``harnesses`` limits which families it may touch."""

    model_config = ConfigDict(extra="forbid")

    blob_id: str = Field(max_length=64)
    blob_sha256: str = Field(min_length=64, max_length=64)
    digest: str = Field(max_length=64)
    harnesses: List[str] = Field(default_factory=list, max_length=4)


@router.put("/blobs/{blob_id}")
async def put_chunk(blob_id: str, request: Request, offset: int = Query(ge=0), caller: str = Depends(_main)) -> Any:
    """Append one chunk at exactly the current size (the sender resumes from ``received`` on a 409). Output: {received}."""
    _cap_body(request, blobs.CHUNK_BYTES)
    data = await request.body()
    if len(data) > blobs.CHUNK_BYTES:
        raise HTTPException(413, {"code": "too_large", "detail": "request body is over the limit"})
    box = inbox()
    try:
        await run_in_threadpool(box.purge_stale)
        await run_in_threadpool(_drop_other_alphas, box, caller)
        size = await run_in_threadpool(box.put, blob_id, offset, data, request.headers.get("x-chunk-sha256", ""), caller)
    except blobs.BlobError as exc:
        return _refuse(exc)
    return {"received": size}


@router.post("/blobs/{blob_id}/seal")
async def seal_blob(blob_id: str, body: SealBody, caller: str = Depends(_main)) -> Any:
    """Verify the whole blob (size and sha256) and make it readable. Output: {sealed: true, size}."""
    try:
        await run_in_threadpool(inbox().seal, blob_id, body.size, body.sha256, body.kind)
    except blobs.BlobError as exc:
        return _refuse(exc)
    return {"sealed": True, "size": body.size}


@router.get("/blobs/{blob_id}")
async def blob_status(blob_id: str, caller: str = Depends(_main)) -> Any:
    """How much of a blob is here and whether it is sealed (resume after a link loss). Status only, never the bytes."""
    try:
        return await run_in_threadpool(inbox().status, blob_id)
    except blobs.BlobError as exc:
        return _refuse(exc)


def _apply(path: Path, harnesses: List[str]) -> gs_apply.Report:
    base = state_dir() / "pack"
    home = home_dir()
    with _APPLY_LOCK:
        return gs_apply.apply_bundle(path, home=home, accounts_root=home / ".carnivore" / "accounts", accounts=local_accounts(),
                                     state=gs_apply.State(base / "global-sync-applied.json"), backups=base / "global-backups",
                                     stage_root=base, harnesses=[h for h in harnesses if h in rules.HARNESSES])


def _install_deps(targets: List[Any]) -> None:
    base = state_dir() / "pack"
    try:
        deps.install_applied(targets, deps.InstallState(base / "global-install-state.json"), Status(base / "global-install-status.json"))
    except Exception:  # noqa: BLE001
        logger.exception("pack_global_install_failed")
    resource_push.notify(topics.PACK_GLOBAL_SYNC)


@router.post("/apply")
async def apply(body: ApplyBody, caller: str = Depends(_main)) -> Any:
    """Check the sealed bundle's hash, apply it, delete the blob. Output: ``{report}`` (counts, refusals, the backup folder). Raises 404, 422 ``hash_mismatch`` / ``bad_bundle``."""
    box = inbox()
    try:
        path = await run_in_threadpool(partial(box.sealed_path, body.blob_id, peer=caller))
    except blobs.BlobError as exc:
        return _refuse(exc)
    try:
        if await run_in_threadpool(blobs.file_sha256, str(path)) != body.blob_sha256:
            return JSONResponse({"detail": {"code": "hash_mismatch"}}, status_code=422)
        report = await run_in_threadpool(_apply, path, body.harnesses)
    except gs_apply.ApplyError as exc:
        return JSONResponse({"detail": {"code": exc.code}}, status_code=422)
    finally:
        await run_in_threadpool(box.remove, body.blob_id)
    logger.info("pack_global_applied", written=report.written, unchanged=report.unchanged, removed=report.removed, refused=len(report.refused))
    resource_push.notify(topics.PACK_GLOBAL_SYNC)
    if report.targets:
        wiring.spawn(asyncio.to_thread(_install_deps, report.targets))
    return {"report": report.summary()}


class PanelBody(BaseModel):
    """The alpha's agent panel document (``globalsync/panel.py``); its shape is checked field by field when applied."""

    model_config = ConfigDict(extra="forbid")

    doc: dict


def _panel_on() -> bool:
    wired = machines_runtime.wiring()
    return bool(clean_settings(wired.state.global_sync() if wired is not None else None).get("panel"))


def _apply_panel(doc: dict, request: Request, from_main: bool) -> tuple:
    store = getattr(request.app.state, "ui_preferences_store", None)
    path = state_dir() / "pack" / "panel-stamps.json"
    with panel_merge.LOCK:
        current = ((store.read() or {}).get("values") or {}).get("drawer_arrangement") if store is not None else None
        with closing(open_db()) as conn, _APPLY_LOCK:
            with transaction(conn):
                iid = get_meta(conn, META_INSTALL_ID)
                report, arrangement = panel_merge.receive(conn, doc, iid, current, path, from_main=from_main)
        result = None
        if arrangement is not None and store is not None:
            result = store.update({"drawer_arrangement": arrangement})
            committed = (result.values or {}).get("drawer_arrangement") if result.status in ("committed", "unchanged") else None
            if isinstance(committed, dict):
                with closing(open_db()) as conn:
                    panel_merge.rebaseline(conn, committed, iid, path, member=from_main)
    return report, arrangement, store, result


async def _receive_panel(body: PanelBody, request: Request, *, from_main: bool) -> Any:
    _cap_body(request, MAX_PANEL_BYTES)
    if not await run_in_threadpool(_panel_on):
        return JSONResponse({"detail": {"code": "panel_off"}}, status_code=403)
    report, arrangement, store, result = await run_in_threadpool(_apply_panel, body.doc, request, from_main)
    if arrangement is None:
        return JSONResponse({"detail": {"code": "bad_panel"}}, status_code=422)
    moved = bool(report["companies_created"] or report["companies_updated"] or report["projects_updated"])
    if report["groups_changed"]:
        session_change_notice.publish(request.app.state, session_change_notice.build_structural_notice("groups"))
        wiring.groups_changed()
    if result is not None:
        from src.core.preferences_push.broadcast import broadcast_changed

        if result.status == "committed":
            moved = True
            await broadcast_changed(request.app.state, result, None)
        elif result.status != "unchanged":
            report["arrangement"] = result.status
    if moved:
        resource_push.notify(topics.PROJECTS)
        resource_push.notify(topics.COMPANIES)
    logger.info("pack_panel_applied", companies=report["companies_created"], projects=report["projects_updated"], groups=report["groups_changed"], two_way=not from_main)
    return {"report": report}


@router.post("/panel")
async def apply_panel(body: PanelBody, request: Request, caller: str = Depends(_main)) -> Any:
    """Apply the alpha's agent panel field by field (the newer edit stamp wins; a tie takes the alpha's value): companies and project names, membership and colors for the projects held here, hand-made session groups (name, members, order, band), and the pins, row order, bands and section order. Folds and every show/hide setting stay this computer's own. Output: ``{report}``. Raises 403 ``panel_off``, 413, 422 ``bad_panel``."""
    return await _receive_panel(body, request, from_main=True)


async def _member(principal: Principal = Depends(_require_machine)) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer sends panel changes"})
    peer = principal.grant.peer_install_id

    def check() -> Optional[str]:
        with closing(open_db()) as conn:
            if content_alpha() != read_install_id(conn):
                return "not_alpha"
        return None if approval.reader(open_db)(peer) else "not_approved"

    refused = await run_in_threadpool(check)
    if direction.contained(peer):
        refused = direction.REFUSAL_CODE
    if refused:
        raise HTTPException(403, {"code": refused, "detail": "only the main takes panel changes, from a computer its owner approved and holds two way"})
    return peer


@router.post("/panel-change")
async def apply_panel_change(body: PanelBody, request: Request, caller: str = Depends(_member)) -> Any:
    """The main takes a member's panel edits (two-way, #2960): the same field-by-field merge, then its own pass carries the result to every other computer. Output: ``{report}``. Raises 403 ``not_alpha`` / ``not_approved`` / ``computer_one_way`` / ``panel_off``, 413, 422 ``bad_panel``."""
    return await _receive_panel(body, request, from_main=False)
