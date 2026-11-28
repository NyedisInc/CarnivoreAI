
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core.resource_push import topics
from src.plugins.host import identity, inspector_telemetry, plugin_channels, risk, runtime, state as owner_state, ui_slots
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.plugins.host.sidecar_registry import SidecarDefinition

logger = structlog.get_logger()

router = APIRouter(
    prefix="/cplugs",
    tags=["cplugs"],
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _resolve_plugin(request: Request, cplug_id: str) -> tuple[runtime.Host, str, Any]:
    host = runtime.host_for(request.app)
    canonical = runtime.canonical_id(cplug_id)
    defn = runtime.find(canonical)
    if defn is None:
        raise _error(404, "cplug_unknown", f"no plugin {cplug_id}")
    return host, canonical, defn


def _resolve_sidecar(request: Request, cplug_id: str) -> tuple[runtime.Host, str, SidecarDefinition, Any]:
    host, canonical, defn = _resolve_plugin(request, cplug_id)
    if not isinstance(defn, SidecarDefinition):
        raise _error(409, "cplug_not_sidecar", f"{canonical} is a built-in plugin and cannot be paused or resumed")
    live = host.sidecar_runtime()
    if live is None:
        raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
    return host, canonical, defn, live


@router.get("/{cplug_id}/inspector")
async def get_cplug_inspector(cplug_id: str, request: Request) -> Dict[str, Any]:
    """Return unified runtime telemetry snapshot (watchdog, surfaces, dev lease, RPC/CLI trace, capability checks, logs)."""
    host, canonical, defn = _resolve_plugin(request, cplug_id)
    live = host.sidecar_runtime()
    supervisor = getattr(live, "supervisor", None) if live is not None else None
    meta = identity.trust_metadata(defn)
    is_sidecar = isinstance(defn, SidecarDefinition)
    install_key = ""
    if is_sidecar:
        try:
            install_key = host.install_key(defn.id)
        except Exception:  # noqa: BLE001
            install_key = getattr(defn, "install_key", "") or ""
    data_dir = getattr(defn, "folder", None) if is_sidecar else None
    return await run_in_threadpool(
        inspector_telemetry.build_snapshot_blocking,
        host.state_dir,
        supervisor,
        defn.id,
        canonical_id=canonical,
        install_key=install_key,
        kind=meta["kind"],
        trust_tier=meta["trust_tier"],
        trust_badge=meta["trust_badge"],
        unverified=meta["unverified"],
        defn=defn,
        data_dir=data_dir,
    )


@router.post("/{cplug_id}/pause")
async def pause_cplug(cplug_id: str, request: Request) -> Dict[str, Any]:
    """Pause an installed sidecar plugin's runtime and block lazy-respawn until resumed or restarted."""
    host, canonical, defn, live = _resolve_sidecar(request, cplug_id)
    from src.plugins.host import dev_routes  # noqa: PLC0415

    async with dev_routes.reload_lock(live.state_dir, defn.id):
        host, canonical, defn, live = _resolve_sidecar(request, cplug_id)
        state = await live.supervisor.pause(defn.id)
        await run_in_threadpool(
            lambda: (
                plugin_channels.sync_plugin(
                    host,
                    defn,
                    safe_mode_active=any(live.safe_mode().values()),
                    supervisor=live.supervisor,
                    tier0_registry=live.tier0_channels,
                ),
                ui_slots.registry_for(host.state_dir).sync(
                    runtime.listed(),
                    host=host,
                    safe_mode_active=any(live.safe_mode().values()),
                    supervisor=live.supervisor,
                ),
            )
        )
        logger.info("cplug_paused", cplug=defn.id)
        host.publish(runtime.CPLUGS_TOPIC)
        host.publish(topics.CPLUG_SLOTS)
        inspector_telemetry.telemetry_for(host.state_dir).notify(defn.id, canonical)
        return {
            "id": canonical,
            "paused": True,
            "runtime_paused": True,
            "state": state,
        }


@router.post("/{cplug_id}/resume")
async def resume_cplug(cplug_id: str, request: Request) -> Dict[str, Any]:
    """Resume a paused sidecar plugin and re-activate it."""
    host, canonical, defn, live = _resolve_sidecar(request, cplug_id)
    from src.plugins.host import dev_routes  # noqa: PLC0415

    async with dev_routes.reload_lock(live.state_dir, defn.id):
        host, canonical, defn, live = _resolve_sidecar(request, cplug_id)
        if not await run_in_threadpool(host.enabled, defn.id):
            raise _error(409, "cplug_disabled", f"turn {defn.id} on before resuming it")
        st = await run_in_threadpool(owner_state.get, host.state_dir, defn.manifest)
        if risk.consent_owed(defn.manifest.tier, defn.manifest.code_digest, st.digest):
            raise _error(409, "needs_approval", f"{defn.id} changed since it was approved; approve it before resuming it")
        spec = host.sidecar_spec(defn)
        after = await live.supervisor.resume(spec)
        await run_in_threadpool(
            lambda: (
                plugin_channels.sync_plugin(
                    host,
                    defn,
                    safe_mode_active=any(live.safe_mode().values()),
                    supervisor=live.supervisor,
                    tier0_registry=live.tier0_channels,
                ),
                ui_slots.registry_for(host.state_dir).sync(
                    runtime.listed(),
                    host=host,
                    safe_mode_active=any(live.safe_mode().values()),
                    supervisor=live.supervisor,
                ),
            )
        )
        paused = live.supervisor.is_paused(defn.id)
        logger.info("cplug_resumed", cplug=defn.id, state=after, paused=paused)
        host.publish(runtime.CPLUGS_TOPIC)
        host.publish(topics.CPLUG_SLOTS)
        inspector_telemetry.telemetry_for(host.state_dir).notify(defn.id, canonical)
        return {
            "id": canonical,
            "paused": paused,
            "runtime_paused": paused,
            "state": after,
        }
