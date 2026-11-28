
from __future__ import annotations

import asyncio
import os
import shutil
import time
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from src.api.auth import require_auth
from src.plugins.host import dev_lease, dev_stream, inspector_telemetry, risk, runtime, sideload, sideload_routes, sidecar_ui, ui_doc
from src.plugins.host import state as owner_state
from src.plugins.host.owner_switch import _runtime as _sidecar_runtime
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import frames
from src.plugins.runtime.process import ProcessEnded

logger = structlog.get_logger()

router = APIRouter(
    prefix="/cplug-owner/dev",
    tags=["cplugs"],
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)

_RELOAD_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[Tuple[str, str], asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


def reload_lock(state_dir: Path, plugin_id: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    bucket = _RELOAD_LOCKS.get(loop)
    if bucket is None:
        bucket = {}
        _RELOAD_LOCKS[loop] = bucket
    key = (os.path.realpath(state_dir), plugin_id)
    lock = bucket.get(key)
    if lock is None:
        lock = asyncio.Lock()
        bucket[key] = lock
    return lock


class LeaseAcquireBody(BaseModel):
    """Request body to acquire a Dev Trust Lease for an installed consented local plugin."""

    model_config = ConfigDict(extra="forbid")
    path: StrictStr
    name: Optional[StrictStr] = None
    ttl_seconds: float = Field(default=dev_lease.DEFAULT_TTL_SECONDS, ge=dev_lease.MIN_TTL_SECONDS, le=dev_lease.MAX_TTL_SECONDS)


class LeaseRenewBody(BaseModel):
    """Request body to renew an existing Dev Trust Lease."""

    model_config = ConfigDict(extra="forbid")
    lease_token: Optional[StrictStr] = None
    ttl_seconds: float = Field(default=dev_lease.DEFAULT_TTL_SECONDS, ge=dev_lease.MIN_TTL_SECONDS, le=dev_lease.MAX_TTL_SECONDS)


class DevReloadBody(BaseModel):
    """Request body to stage and fast-reload a local dev plugin under an active lease."""

    model_config = ConfigDict(extra="forbid")
    path: StrictStr
    name: Optional[StrictStr] = None
    probe_ui: StrictBool = True


def _err(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail, **extra})


def _validate_local_source(raw_path: str) -> Path:
    p = Path(raw_path)
    if not p.is_absolute() or p.is_symlink() or not p.is_dir():
        raise _err(422, "source_missing", "give the absolute path of a real plugin folder (not a symlink)")
    return Path(os.path.realpath(p))


def _record_stderr(stream: dev_stream.DevEventStream, plugin_id: str, proc: Any) -> None:
    if proc is None:
        return
    raw_stderr = getattr(proc, "stderr", None)
    if raw_stderr:
        text = bytes(raw_stderr).decode("utf-8", errors="replace").strip()
        if text:
            stream.publish(plugin_id, "stderr", {"text": text[-2000:]})


@router.post("/lease")
async def post_dev_lease(body: LeaseAcquireBody, request: Request) -> Dict[str, Any]:
    """Acquire a Dev Trust Lease for an already-consented local plugin directory."""
    live = _sidecar_runtime(request)
    state_dir = live.state_dir
    sideload_routes.require_on(state_dir)
    source = _validate_local_source(body.path)
    try:
        plugin_id = await asyncio.to_thread(sideload_routes.name_of, source, body.name)
    except sideload.SideloadRefused as exc:
        raise sideload_routes._refuse(exc) from exc
    host = runtime.host_for(request.app)
    d = runtime.find(plugin_id)
    if not isinstance(d, SidecarDefinition) or d.manifest.tier != sideload.TIER_LOCAL:
        raise _err(404, "cplug_unknown", f"local plugin {plugin_id} is not installed/synced yet")
    st = await run_in_threadpool_fn(owner_state.get, state_dir, d.manifest)
    if not st.enabled or risk.consent_owed(sideload.TIER_LOCAL, d.manifest.code_digest, st.digest):
        raise _err(409, "needs_approval", f"{plugin_id} must be enabled and consented before acquiring a dev lease")
    try:
        install_key = host.install_key(plugin_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("cplug_dev_lease_key_failed", plugin_id=plugin_id, error_type=type(exc).__name__)
        raise _err(503, "install_ledger_unreadable", "install ledger could not be read") from exc
    lease = dev_lease.store_for(state_dir).acquire(
        plugin_id,
        install_key,
        source,
        d.manifest,
        ttl=body.ttl_seconds,
    )
    dev_stream.stream_for(state_dir).publish(
        plugin_id,
        "lease_acquired",
        {"baseline_sha": lease.baseline_sha, "expires_at": lease.expires_at},
    )
    inspector_telemetry.telemetry_for(state_dir).notify(plugin_id)
    logger.info("cplug_dev_lease_acquired", plugin_id=plugin_id, baseline_sha=lease.baseline_sha[:12])
    return {
        "plugin_id": lease.plugin_id,
        "install_key": lease.install_key,
        "source_realpath": lease.source_realpath,
        "baseline_sha": lease.baseline_sha,
        "expires_at": lease.expires_at,
        "ttl_seconds": body.ttl_seconds,
        "lease_token": lease.lease_token,
    }


@router.put("/lease/{plugin_id}")
async def put_dev_lease(plugin_id: str, body: LeaseRenewBody, request: Request) -> Dict[str, Any]:
    """Renew an active Dev Trust Lease TTL."""
    live = _sidecar_runtime(request)
    sideload_routes.require_on(live.state_dir)
    lease = dev_lease.store_for(live.state_dir).renew(
        plugin_id,
        ttl=body.ttl_seconds,
        lease_token=body.lease_token,
    )
    if lease is None:
        raise _err(404, "lease_not_found", f"no active dev lease for {plugin_id}")
    inspector_telemetry.telemetry_for(live.state_dir).notify(plugin_id)
    return {
        "plugin_id": lease.plugin_id,
        "baseline_sha": lease.baseline_sha,
        "expires_at": lease.expires_at,
        "ttl_seconds": body.ttl_seconds,
    }


@router.delete("/lease/{plugin_id}")
async def delete_dev_lease(plugin_id: str, request: Request) -> Dict[str, Any]:
    """Explicitly release a Dev Trust Lease on ``carnivore plugin dev`` exit."""
    live = _sidecar_runtime(request)
    released = dev_lease.store_for(live.state_dir).revoke_plugin(plugin_id)
    if released:
        dev_stream.stream_for(live.state_dir).publish(plugin_id, "lease_released", {})
        inspector_telemetry.telemetry_for(live.state_dir).notify(plugin_id)
    return {"plugin_id": plugin_id, "released": released}


@router.post("/reload")
async def post_dev_reload(body: DevReloadBody, request: Request) -> Dict[str, Any]:
    """Fast-stage and hot-reload a local dev plugin in <300ms while Dev Trust Lease holds."""
    t_total_start = time.perf_counter()
    live = _sidecar_runtime(request)
    state_dir = live.state_dir
    sideload_routes.require_on(state_dir)
    if any(live.safe_mode().values()):
        raise _err(409, "cplug_disabled", "plugin runtime is in safe mode or disabled")

    source = _validate_local_source(body.path)
    stream = dev_stream.stream_for(state_dir)
    host = runtime.host_for(request.app)

    t_stage_start = time.perf_counter()
    try:
        plugin_id = await asyncio.to_thread(sideload_routes.name_of, source, body.name)
    except sideload.SideloadRefused as exc:
        raise sideload_routes._refuse(exc) from exc

    async with reload_lock(state_dir, plugin_id):
        existing = runtime.find(plugin_id)
        if not isinstance(existing, SidecarDefinition) or existing.manifest.tier != sideload.TIER_LOCAL:
            raise _err(404, "cplug_unknown", f"local plugin {plugin_id} is not installed")
        try:
            install_key = host.install_key(plugin_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("cplug_dev_reload_key_failed", plugin_id=plugin_id, error_type=type(exc).__name__)
            raise _err(503, "install_ledger_unreadable", "install ledger could not be read") from exc

        st_existing = await asyncio.to_thread(owner_state.get, state_dir, existing.manifest)
        if not st_existing.enabled or risk.consent_owed(sideload.TIER_LOCAL, existing.manifest.code_digest, st_existing.digest):
            dev_lease.store_for(state_dir).revoke_plugin(plugin_id)
            raise _err(
                409,
                "needs_approval",
                f"{plugin_id} must be enabled and consented before dev reload",
                needs_approval=True,
            )

        try:
            staging, files, manifest = await asyncio.to_thread(sideload.stage, state_dir, plugin_id, source, dev=True)
        except sideload.SideloadRefused as exc:
            stream.publish(plugin_id, "reload_error", {"code": exc.code, "detail": str(exc)})
            raise sideload_routes._refuse(exc) from exc

        stage_ms = round((time.perf_counter() - t_stage_start) * 1000.0, 2)
        digest = manifest.code_digest
        leases = dev_lease.store_for(state_dir)
        ok, reason, widened = leases.check_reload(plugin_id, install_key, source, manifest)
        if not ok:
            if reason == "source_mismatch":
                shutil.rmtree(staging, ignore_errors=True)
                stream.publish(
                    plugin_id,
                    "reload_error",
                    {"code": "source_mismatch", "detail": "source path does not match active lease"},
                )
                raise _err(
                    409,
                    "source_mismatch",
                    f"{plugin_id} dev reload source path does not match active lease",
                )
            if reason == "permission_widened":
                await live.supervisor.disable(plugin_id, "sideload", stop_timeout=0.05)
                staged = {"name": plugin_id, "digest": digest, "staging": staging, "files": files, "manifest": manifest}
                try:
                    await asyncio.to_thread(sideload_routes._commit_blocking, state_dir, source, staged)
                except Exception as exc:  # noqa: BLE001
                    shutil.rmtree(staging, ignore_errors=True)
                    logger.error("cplug_dev_widened_commit_failed", plugin_id=plugin_id, error_type=type(exc).__name__)
                    raise _err(500, "sideload_failed", "staged files could not be committed") from exc
                await asyncio.to_thread(owner_state.strip_consent, state_dir, plugin_id)
                await asyncio.to_thread(live.reload_one, plugin_id, item_id=existing.item_id, immediate_ui=True)
                stream.publish(plugin_id, "permission_widened", {"reason": reason, "widened": widened})
                raise _err(
                    409,
                    reason,
                    f"{plugin_id} widened capabilities ({', '.join(widened) or reason}); re-consent required",
                    widened=widened,
                    needs_approval=True,
                )
            shutil.rmtree(staging, ignore_errors=True)
            raise _err(409, "lease_required", f"active dev trust lease required ({reason})")

        if sideload.unchanged(state_dir, plugin_id, digest):
            shutil.rmtree(staging, ignore_errors=True)
            total_ms = round((time.perf_counter() - t_total_start) * 1000.0, 2)
            return {
                "id": plugin_id,
                "status": "unchanged",
                "unchanged": True,
                "needs_approval": False,
                "digest": digest,
                "timings": {"stage_ms": stage_ms, "stop_ms": 0.0, "start_ms": 0.0, "total_ms": total_ms},
            }

        t_stop_start = time.perf_counter()
        old_proc = live.supervisor.process(plugin_id)
        await live.supervisor.disable(plugin_id, "restart", stop_timeout=0.05)
        _record_stderr(stream, plugin_id, old_proc)
        stop_ms = round((time.perf_counter() - t_stop_start) * 1000.0, 2)

        staged = {"name": plugin_id, "digest": digest, "staging": staging, "files": files, "manifest": manifest}
        try:
            changed = await asyncio.to_thread(sideload_routes._commit_blocking, state_dir, source, staged)
            await asyncio.to_thread(
                owner_state.update,
                state_dir,
                manifest,
                None,
                lambda st: replace(st, digest=digest, enabled=True),
            )
            defn = await asyncio.to_thread(live.reload_one, plugin_id, item_id=existing.item_id, immediate_ui=True)
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(staging, ignore_errors=True)
            logger.error("cplug_dev_reload_commit_failed", plugin_id=plugin_id, error_type=type(exc).__name__)
            raise _err(500, "sideload_failed", "dev reload commit failed") from exc

        t_start_start = time.perf_counter()
        proc_state = "unknown"
        ui_error: Optional[Dict[str, str]] = None
        if defn is not None:
            spec = host.sidecar_spec(defn)
            proc_state = await live.supervisor.enable(spec)
            proc = live.supervisor.process(plugin_id)
            _record_stderr(stream, plugin_id, proc)
            if body.probe_ui and proc is not None and not defn.manifest.tier0 and proc_state == "running":
                ui_error = await _probe_dev_ui(proc, defn, stream)
        start_ms = round((time.perf_counter() - t_start_start) * 1000.0, 2)
        total_ms = round((time.perf_counter() - t_total_start) * 1000.0, 2)

        payload = {
            "id": plugin_id,
            "status": "reloaded",
            "unchanged": False,
            "needs_approval": False,
            "digest": digest,
            "changed": changed,
            "process": proc_state,
            "ui_error": ui_error,
            "timings": {"stage_ms": stage_ms, "stop_ms": stop_ms, "start_ms": start_ms, "total_ms": total_ms},
        }
        stream.publish(plugin_id, "reloaded", payload)
        inspector_telemetry.telemetry_for(state_dir).notify(plugin_id)
        logger.info("cplug_dev_reloaded", plugin_id=plugin_id, total_ms=total_ms, process=proc_state)
        return payload


async def _probe_dev_ui(proc: Any, defn: SidecarDefinition, stream: dev_stream.DevEventStream) -> Optional[Dict[str, str]]:
    try:
        rendered = await sidecar_ui._render(proc, "widget", {})
        ui_doc.validate(
            rendered,
            routes=defn.manifest.routes,
            tools=[t.get("name") for t in defn.manifest.tools if isinstance(t, dict)],
        )
        return None
    except sidecar_ui.NoSuchSurface:
        return None
    except ui_doc.UiDocError as exc:
        err = {"code": exc.code, "path": exc.path}
        stream.publish(defn.id, "ui_error", err)
        return err
    except (RuntimeError, frames.FrameViolation, ProcessEnded) as exc:
        err = {"code": type(exc).__name__, "detail": str(exc)[:200]}
        stream.publish(defn.id, "ui_error", err)
        return err


@router.get("/stream/{plugin_id}")
async def get_dev_stream(
    plugin_id: str,
    request: Request,
    after_seq: int = Query(0, ge=0),
    once: bool = Query(False),
) -> StreamingResponse:
    """Stream live dev stderr, reload events, RPC traces, and UI validation errors via SSE."""
    live = _sidecar_runtime(request)
    stream = dev_stream.stream_for(live.state_dir)
    return StreamingResponse(
        stream.subscribe(plugin_id, after_seq=after_seq, replay_only=once),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def run_in_threadpool_fn(fn: Any, *args: Any) -> Any:
    return await asyncio.to_thread(fn, *args)
