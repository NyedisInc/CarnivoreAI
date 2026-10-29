
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, StrictStr

from src.cplugs.host import runtime
from src.cplugs.host.activity_log import ActivityLog
from src.cplugs.host.egress_log import EgressLog
from src.cplugs.host import identity
from src.cplugs.host.secret_store import SecretError, SecretStore

logger = structlog.get_logger()

router = APIRouter()
_STATUS = {"secret_unknown": 404, "secret_unbound": 422, "secret_invalid": 422, "keychain_refused": 503,
           "secrets_unreadable": 503, "secrets_unwritable": 503}


class SecretBody(BaseModel):

    model_config = ConfigDict(extra="forbid")
    value: StrictStr


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _shipped(cplug_id: str) -> Any:
    d = runtime.find(cplug_id)
    if d is None:
        raise _error(404, "cplug_unknown", f"no plugin {cplug_id}")
    return d


@router.put("/{cplug_id}/secrets/{name}")
async def put_secret(cplug_id: str, name: str, body: SecretBody, request: Request) -> Dict[str, bool]:
    """Store a secret value, bound to the hosts the manifest declares for it now. Output: its status (never the value)."""
    host = runtime.host_for(request.app)
    d = _shipped(cplug_id)
    store = SecretStore(host.state_dir)
    try:
        await run_in_threadpool(store.set, host.install_key(cplug_id), d.manifest, name, body.value)
    except SecretError as exc:
        raise _error(_STATUS.get(exc.code, 422), exc.code, str(exc)) from exc
    return await run_in_threadpool(store.status, host.install_key(cplug_id), d.manifest, name)


@router.get("/{cplug_id}/secrets/{name}")
async def get_secret(cplug_id: str, name: str, request: Request) -> Dict[str, bool]:
    """Whether a value is stored for the hosts the manifest declares now. Output: {secret_present, needs_reentry}."""
    host = runtime.host_for(request.app)
    d = _shipped(cplug_id)
    if name not in {s.name for s in d.manifest.network.secrets}:
        raise _error(404, "secret_unknown", f"{cplug_id} declares no secret {name}")
    try:
        return await run_in_threadpool(SecretStore(host.state_dir).status, host.install_key(cplug_id), d.manifest, name)
    except SecretError as exc:
        raise _error(_STATUS.get(exc.code, 503), exc.code, str(exc)) from exc


@router.delete("/{cplug_id}/secrets/{name}")
async def delete_secret(cplug_id: str, name: str, request: Request) -> Dict[str, bool]:
    """Remove a stored value and its binding. Output: {secret_present: false, needs_reentry: false}."""
    host = runtime.host_for(request.app)
    d = _shipped(cplug_id)
    if name not in {s.name for s in d.manifest.network.secrets}:
        raise _error(404, "secret_unknown", f"{cplug_id} declares no secret {name}")
    try:
        await run_in_threadpool(SecretStore(host.state_dir).delete, host.install_key(cplug_id), name)
    except SecretError as exc:
        raise _error(_STATUS.get(exc.code, 503), exc.code, str(exc)) from exc
    return {"secret_present": False, "needs_reentry": False}


@router.get("/{cplug_id}/egress")
async def get_egress(cplug_id: str, request: Request, limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """The plugin's recent requests and refusals, newest first (the detail pane's egress list). Output: {rows}."""
    host = runtime.host_for(request.app)
    _shipped(cplug_id)
    try:
        rows = await run_in_threadpool(EgressLog(host.state_dir).recent, host.install_key(cplug_id), limit)
    except (sqlite3.Error, OSError) as exc:
        raise _error(503, "egress_unreadable", "the egress log could not be read") from exc
    return {"rows": rows}


def purge_network_data(state_dir: Any, cplug_id: str) -> List[str]:
    """
    Inputs: state_dir (Path); cplug_id (str). Output: the stores whose delete failed, in order, from
    ``install_key`` (the ledger could not name the key, so nothing was tried), ``keychain``, ``egress``, ``activity``;
    empty on full success. Each store is tried even when an earlier one failed. A failure is logged, never raised: the
    caller decides whether the install's name may be released, and a second purge retries.
    """
    try:
        key = runtime.install_key_for(state_dir, cplug_id)
    except identity.LedgerUnreadable as exc:
        logger.warning("cplug_network_purge_failed", cplug=cplug_id, store="install_key", error_type=type(exc).__name__)
        return ["install_key"]
    failed: List[str] = []
    for store, delete in (("keychain", lambda: SecretStore(state_dir).purge(key)), ("egress", lambda: EgressLog(state_dir).forget(key)),
                          ("activity", lambda: ActivityLog(state_dir).forget(key))):
        try:
            delete()
        except (SecretError, sqlite3.Error, OSError) as exc:
            logger.warning("cplug_network_purge_failed", cplug=cplug_id, store=store, error_type=type(exc).__name__)
            failed.append(store)
    return failed
