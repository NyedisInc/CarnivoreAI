
from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.skills import kinds
from src.core.skills.consent_via_ddl import CONSENT_SHEET
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem
from src.cplugs.host import identity, risk, runtime, sideload, sideload_git
from src.cplugs.host import state as owner_state
from src.cplugs.host.owner_switch import _runtime as _sidecar_runtime

logger = structlog.get_logger()

router = APIRouter(prefix="/cplug-owner", tags=["cplugs"], dependencies=[Depends(require_auth)])
SOURCE = "sideload"
CPLUGS_TOPIC = "cplugs"


class SyncBody(BaseModel):
    """The folder to sideload and, optionally, the install name (default: the ``id`` in its ``cplug.json``)."""

    model_config = ConfigDict(extra="forbid")
    path: StrictStr
    name: Optional[StrictStr] = None


class SwitchBody(BaseModel):
    """The sideload switch the owner chose and, turning it on, for how long (``hours``; omitted is twelve, null until turned off)."""

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    hours: Any = None


def _refuse(exc: sideload.SideloadRefused) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc)})


@contextlib.contextmanager
def _ledger(state_dir: Path) -> Iterator[InstallLedger]:
    conn = connect(db_path_for(state_dir), create=False)
    try:
        yield InstallLedger(conn)
    finally:
        conn.close()


def _stamp() -> str:
    return datetime.fromtimestamp(sideload.wall(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reload(live: Any) -> None:
    live.load_registry()
    from src.core import resource_push  # noqa: PLC0415

    resource_push.notify(CPLUGS_TOPIC)


async def _stop(live: Any, name: str, *, forget: bool = False) -> None:
    await live.supervisor.disable(name, "sideload")
    await asyncio.to_thread(live.effects.cancel, name)
    if forget:
        live.supervisor.forget(name)


async def stop_all_local(live: Any) -> None:
    for name in list(sideload.items(live.state_dir)):
        await _stop(live, name)
    await asyncio.to_thread(_reload, live)


def arm_expiry(app: Any, live: Any) -> None:
    handle = getattr(app.state, "sideload_expiry", None)
    if handle is not None:
        handle.cancel()
    end = sideload.expires_at(live.state_dir)
    loop = asyncio.get_running_loop()
    if end is None or not sideload.is_on(live.state_dir, sideload.wall):
        app.state.sideload_expiry = None
        return
    app.state.sideload_expiry = loop.call_later(max(0.0, end - sideload.wall()) + 1.0, lambda: loop.create_task(_expired(live)))


async def _expired(live: Any) -> None:
    if not sideload.is_on(live.state_dir, sideload.wall):
        await stop_all_local(live)


def _status(state_dir: Path) -> Dict[str, Any]:
    on = sideload.is_on(state_dir, sideload.wall)
    return {"enabled": on, "expires_at": sideload.expires_at(state_dir) if on else None, "hours": sideload.duration_hours(state_dir),
            "items": [{"id": n, "item_id": f"{sideload.LOCAL_PUBLISHER}/{n}", "source": v.get("source", ""), "synced_at": v.get("synced_at"),
                       "changed": v.get("changed") or [], "git": sideload_git.describe(state_dir, n, v.get("source", ""))}
                      for n, v in sorted(sideload.items(state_dir).items())]}


@router.get("/sideload")
async def get_sideload(request: Request) -> Dict[str, Any]:
    """The sideload switch and what was sideloaded. Output: status."""
    return _status(_sidecar_runtime(request).state_dir)


@router.put("/sideload/switch")
async def put_switch(body: SwitchBody, request: Request) -> Dict[str, Any]:
    """Turn the developer sideload switch on (for ``hours``) or off (every sideloaded plugin stops and is hidden). Output: status."""
    live = _sidecar_runtime(request)
    hours = body.hours if "hours" in body.model_fields_set else sideload.DEFAULT_HOURS
    if not sideload.valid_duration(hours):
        raise HTTPException(status_code=422, detail={"code": "duration_invalid",
                                                     "detail": f"hours is one of {list(sideload.DURATION_HOURS)}, or null for until turned off"})
    if not await asyncio.to_thread(sideload.set_switch, live.state_dir, body.enabled, sideload.wall, hours):
        raise HTTPException(status_code=500, detail={"code": "switch_not_saved", "detail": "the switch could not be written; it is unchanged"})
    arm_expiry(request.app, live)
    if not body.enabled:
        await stop_all_local(live)
    else:
        await asyncio.to_thread(_reload, live)
    return _status(live.state_dir)


def name_of(source: Path, given: Optional[str]) -> str:
    if given is not None:
        if not isinstance(given, str) or not identity.INSTALL_NAME.match(given):
            raise sideload.SideloadRefused("name_invalid", f"an install name must match {identity.INSTALL_NAME.pattern}", 409)
        return given
    try:
        found = json.loads((source / "cplug.json").read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError, AttributeError):
        found = None
    if not isinstance(found, str) or not identity.INSTALL_NAME.match(found):
        raise sideload.SideloadRefused("source_missing", "the folder has no readable cplug.json with a valid id", 422)
    return found


def _sync_blocking(state_dir: Path, source: Path, given: Optional[str]) -> Dict[str, Any]:
    name = name_of(source, given)
    staging, files, manifest = sideload.stage(state_dir, name, source)
    digest = manifest.code_digest
    try:
        if sideload.unchanged(state_dir, name, digest):
            shutil.rmtree(staging, ignore_errors=True)
            sideload.touch(state_dir, name, source, sideload.wall)
            return {"name": name, "digest": digest, "unchanged": True, "staging": None, "manifest": manifest}
        shipped = frozenset(d.id for d in runtime.definitions())
        identity.register_install(state_dir, name, f"{sideload.LOCAL_PUBLISHER}/{name}", shipped)
    except identity.InstallRefused as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise HTTPException(status_code=409, detail={"code": exc.code, "detail": str(exc)}) from exc
    except identity.LedgerUnreadable as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise HTTPException(status_code=409, detail={"code": "cplug_ledger_unreadable", "detail": "the plugin install ledger cannot be read"}) from exc
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"name": name, "digest": digest, "unchanged": False, "staging": staging, "files": files, "manifest": manifest}


def _commit_blocking(state_dir: Path, source: Path, staged: Dict[str, Any]) -> list:
    name, manifest = staged["name"], staged["manifest"]
    try:
        changed = sideload.install_staged(state_dir, name, staged["staging"], staged["files"], staged["digest"], source, sideload.wall)
        with _ledger(state_dir) as ledger:
            item_id = f"{sideload.LOCAL_PUBLISHER}/{name}"
            row = ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
            if row is None:
                ledger.insert(InstalledItem(
                    install_id=identity.lookup(state_dir, name).uuid, item_id=item_id, kind=kinds.KIND_CPLUG, publisher=sideload.LOCAL_PUBLISHER,
                    name=f"cplug-{sideload.LOCAL_PUBLISHER}-{name}", version=manifest.version, digest=staged["digest"], scope=SCOPE_GLOBAL,
                    project_path=GLOBAL_PROJECT_PATH, auto_update=False, source_index_url=SOURCE, consented_digest=None, consented_body_sha=None,
                    publisher_key_id=SOURCE, revision=1, installed_at=_stamp(), updated_at=_stamp(), consent_via=CONSENT_SHEET))
            else:
                ledger.update(row.install_id, expected_revision=row.revision, now=_stamp(), version=manifest.version, digest=staged["digest"])
    except BaseException:
        shutil.rmtree(staged["staging"], ignore_errors=True)
        raise
    return changed


def require_on(state_dir: Path) -> None:
    if not sideload.is_on(state_dir, sideload.wall):
        raise HTTPException(status_code=409, detail={"code": "sideload_off", "detail": "the developer sideload switch is off"})


@router.post("/sideload")
async def post_sideload(body: SyncBody, request: Request) -> Dict[str, Any]:
    """Copy a folder into the code root and register it as ``local/<name>`` (or re-sync it). Output: {id, digest, unchanged, changed, needs_approval}."""
    live = _sidecar_runtime(request)
    require_on(live.state_dir)
    return await sync_folder(live, Path(body.path), body.name)


async def sync_folder(live: Any, source: Path, given: Optional[str]) -> Dict[str, Any]:
    state_dir = live.state_dir
    try:
        staged = await asyncio.to_thread(_sync_blocking, state_dir, source, given)
        manifest = staged["manifest"]
        changed: list = []
        if not staged["unchanged"]:
            await _stop(live, staged["name"])
            changed = await asyncio.to_thread(_commit_blocking, state_dir, source, staged)
            await asyncio.to_thread(_reload, live)
    except sideload.SideloadRefused as exc:
        raise _refuse(exc) from exc
    except (OSError, ValueError) as exc:
        logger.warning("cplug_sideload_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail={"code": "sideload_failed", "detail": "the folder could not be copied or recorded"}) from exc
    held = owner_state.get(state_dir, manifest)
    return {"id": staged["name"], "item_id": f"{sideload.LOCAL_PUBLISHER}/{staged['name']}", "tier": sideload.TIER_LOCAL, "unverified": True,
            "digest": staged["digest"], "unchanged": staged["unchanged"], "changed": changed,
            "needs_approval": held.enabled and risk.consent_owed(sideload.TIER_LOCAL, staged["digest"], held.digest)}


def _delete_blocking(state_dir: Path, name: str) -> bool:
    with _ledger(state_dir) as ledger:
        row = ledger.find(f"{sideload.LOCAL_PUBLISHER}/{name}", SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
        if row is None:
            return False
        ledger.delete(row.install_id)
    shutil.rmtree(sideload.code_root_of(state_dir, name), ignore_errors=True)
    sideload.forget(state_dir, name)
    sideload_git.forget(state_dir, name)
    return True


@router.delete("/sideload")
async def delete_sideload(request: Request, name: str = Query(..., min_length=1, max_length=64)) -> Dict[str, Any]:
    """Remove one sideloaded plugin: stop it, then drop its row and its copied code. Its data and grants stay. Output: {removed}."""
    live = _sidecar_runtime(request)
    if name not in sideload.items(live.state_dir):
        raise HTTPException(status_code=404, detail={"code": "sideload_unknown", "detail": f"{name} is not sideloaded"})
    await _stop(live, name, forget=True)
    try:
        found = await asyncio.to_thread(_delete_blocking, live.state_dir, name)
    except sideload.SideloadRefused as exc:
        raise _refuse(exc) from exc
    if not found:
        raise HTTPException(status_code=404, detail={"code": "sideload_unknown", "detail": f"{name} is not sideloaded"})
    await asyncio.to_thread(_reload, live)
    return {"removed": name}
