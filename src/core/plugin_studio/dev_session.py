
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.core.plugin_studio import inspector_preview, store
from src.core.plugin_studio.errors import StudioActionError, WorkspaceConflictError, WorkspaceValidationError
from src.core import resource_push
from src.plugins.cli import dev_runner
from src.plugins.host import (
    consent as consent_mod,
    dev_lease,
    dev_routes,
    dev_stream,
    developer_mode,
    inspector_telemetry,
    owner_switch,
    risk,
    runtime,
    sideload,
    sideload_routes,
    state as owner_state,
)
from src.plugins.host.sidecar_registry import SidecarDefinition

logger = structlog.get_logger()

DEBOUNCE_SECONDS = dev_runner.DEBOUNCE_MS_DEFAULT / 1000.0
RENEW_INTERVAL_SECONDS = dev_runner.RENEW_INTERVAL_S
LEASE_TTL_SECONDS = dev_runner.LEASE_TTL_S


@dataclass
class _DevWatchEntry:
    studio_id: str
    plugin_id: str
    folder: Path
    task: Optional[asyncio.Task[None]] = None
    last_reload_ms: Optional[float] = None
    last_status: str = "active"
    last_error: Optional[Dict[str, Any]] = None
    reload_count: int = 0
    started_at: str = field(default_factory=store.utc_now_iso)


def _studio_err_from_http(exc: HTTPException, default_code: str = "studio_dev_failed") -> StudioActionError:
    detail_obj = exc.detail
    if isinstance(detail_obj, dict):
        code = str(detail_obj.get("code") or default_code)
        detail = str(detail_obj.get("detail") or code)
        extra = {k: v for k, v in detail_obj.items() if k not in ("code", "detail")}
        return StudioActionError(exc.status_code, code, detail, extra=extra)
    return StudioActionError(exc.status_code, default_code, str(detail_obj or default_code))


def _consent_and_enable_blocking(
    state_dir: Path,
    manifest: Any,
    *,
    auto_approve: bool,
) -> None:
    st = owner_state.get(state_dir, manifest)
    if st.enabled and not risk.consent_owed(sideload.TIER_LOCAL, manifest.code_digest, st.digest):
        return
    if not auto_approve:
        raise WorkspaceConflictError(
            f"{manifest.id} requires approval before enabling",
            code="needs_approval",
            extra={"needs_approval": True},
        )
    sh = consent_mod.sheet(manifest, st.grants, st.ui_slot_grants)
    unexplained = [p for p in manifest.permissions if not consent_mod.reason_for(manifest, p)]
    if unexplained:
        raise WorkspaceValidationError(
            f"{manifest.id} is missing permission reason(s): {', '.join(unexplained)}",
            code="reason_missing",
        )
    declared_slots = consent_mod.declared_ui_slots(manifest)
    consent_body = {
        "digest": sh["digest"],
        "body_sha": sh["body_sha"],
        "grants_sha": sh["grants_sha"],
        "ui_slots_sha": sh["ui_slots_sha"],
        "ticks": [p["name"] for p in sh["permissions"] if p.get("needs_tick")],
        "slot_ticks": [s["slot"] for s in sh.get("ui_slots", []) if s.get("needs_tick")],
    }
    try:
        consent_mod.check(
            manifest,
            manifest.permissions,
            st.grants,
            consent_body,
            requested_slots=declared_slots if declared_slots else None,
            current_slots=st.ui_slot_grants,
        )
    except consent_mod.ConsentRefused as exc:
        raise StudioActionError(exc.status, exc.code, exc.detail) from exc
    owner_state.update(
        state_dir,
        manifest,
        st.revision,
        lambda cur: replace(
            cur,
            enabled=True,
            grants=tuple(manifest.permissions),
            ui_slot_grants=tuple(declared_slots),
            digest=manifest.code_digest,
        ),
    )


class DevSessionManager:

    def __init__(self, app: Any) -> None:
        self._app = app
        self._entries: Dict[str, _DevWatchEntry] = {}
        self._lock = asyncio.Lock()

    def _runtime_and_host(self) -> tuple[Any, Any]:
        live = getattr(self._app.state, "sidecar_runtime", None)
        host = runtime.host_for(self._app)
        if live is None or host is None:
            raise StudioActionError(503, "cplug_runtime_unavailable", "The plugin runtime is not running.")
        return live, host

    def status_for(self, studio_id: str, state_dir: Optional[Path] = None, plugin_id: Optional[str] = None) -> Dict[str, Any]:
        entry = self._entries.get(studio_id)
        lease_info = None
        if state_dir is not None and plugin_id:
            lease = dev_lease.store_for(state_dir).get(plugin_id)
            if lease is not None:
                lease_info = {
                    "plugin_id": lease.plugin_id,
                    "baseline_sha": lease.baseline_sha,
                    "expires_at": lease.expires_at,
                }
        return {
            "active": entry is not None and entry.task is not None and not entry.task.done(),
            "plugin_id": entry.plugin_id if entry else plugin_id,
            "status": entry.last_status if entry else "stopped",
            "reload_count": entry.reload_count if entry else 0,
            "last_reload_ms": entry.last_reload_ms if entry else None,
            "last_error": entry.last_error if entry else None,
            "lease": lease_info,
        }

    async def start(
        self,
        studio_id: str,
        workspace: Dict[str, Any],
        *,
        auto_approve: bool = True,
    ) -> Dict[str, Any]:
        if not developer_mode.is_on():
            raise WorkspaceConflictError(
                "Developer mode is off; enable Developer Mode in settings to run live Studio dev mode.",
                code="developer_mode_off",
            )
        live, host = self._runtime_and_host()
        state_dir = live.state_dir
        folder = store.contained_workspace_folder(state_dir, str(workspace["folder"]))

        if not sideload.allowed(state_dir, sideload.wall):
            if auto_approve and developer_mode.is_on():
                await asyncio.to_thread(sideload.set_switch, state_dir, True)
            else:
                raise WorkspaceConflictError("Sideload switch is off.", code="sideload_off")

        source_check = folder if folder.is_symlink() else Path(os.path.realpath(folder))
        try:
            plugin_name = await asyncio.to_thread(sideload_routes.name_of, source_check, None)
        except sideload.SideloadRefused as exc:
            raise _studio_err_from_http(sideload_routes._refuse(exc), "sideload_failed") from exc

        async with dev_routes.reload_lock(state_dir, plugin_name):
            try:
                sync_res = await sideload_routes.sync_folder(live, folder, None, _lock_held=True)
            except HTTPException as exc:
                raise _studio_err_from_http(exc, "sideload_failed") from exc

            plugin_id = str(sync_res["id"])
            defn = runtime.find(plugin_id)
            if not isinstance(defn, SidecarDefinition) or defn.manifest.tier != sideload.TIER_LOCAL:
                raise StudioActionError(404, "cplug_unknown", f"Local plugin {plugin_id} is not registered after sync.")

            before_enabled = await asyncio.to_thread(host.enabled, plugin_id)
            await asyncio.to_thread(_consent_and_enable_blocking, state_dir, defn.manifest, auto_approve=auto_approve)

            if auto_approve and not await asyncio.to_thread(owner_switch.read, state_dir):
                await asyncio.to_thread(owner_switch.write, state_dir, True)
            if auto_approve and not await live.set_switch(True):
                raise WorkspaceConflictError("Runtime safe mode is forced by environment.", code="safe_mode_forced")

            if not before_enabled:
                await host.switched(plugin_id, True)
            else:
                await host.restart_sidecar(defn)

            if not defn.manifest.tier0 and not any(live.safe_mode().values()):
                proc = live.supervisor.process(plugin_id)
                if (proc is None or bool(getattr(proc, "ended", None))) and live.supervisor.state(plugin_id) == "idle":
                    await live.supervisor.enable(host.sidecar_spec(defn))

            try:
                install_key = await asyncio.to_thread(host.install_key, plugin_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("studio_dev_install_key_failed", studio_id=studio_id, plugin_id=plugin_id, error_type=type(exc).__name__, exc_info=True)
                raise StudioActionError(503, "install_ledger_unreadable", "Install ledger could not be read.") from exc

            lease = dev_lease.store_for(state_dir).acquire(plugin_id, install_key, folder, defn.manifest, ttl=LEASE_TTL_SECONDS)
        dev_stream.stream_for(state_dir).publish(
            plugin_id,
            "lease_acquired",
            {"baseline_sha": lease.baseline_sha, "expires_at": lease.expires_at, "studio_id": studio_id},
        )
        inspector_telemetry.telemetry_for(state_dir).notify(plugin_id)
        await asyncio.to_thread(resource_push.notify, "cplugs")

        initial_snap = await asyncio.to_thread(dev_runner.snapshot_tree, folder)
        async with self._lock:
            existing = self._entries.get(studio_id)
            if existing is not None and existing.task is not None and not existing.task.done():
                existing.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await existing.task
            entry = _DevWatchEntry(studio_id=studio_id, plugin_id=plugin_id, folder=folder)
            entry.task = asyncio.create_task(
                self._watch_loop(entry, initial_snap=initial_snap),
                name=f"studio-dev-{studio_id}",
            )
            self._entries[studio_id] = entry

        store.update_workspace(state_dir, studio_id, lambda row: {**row, "dev_active": True})
        return {
            "active": True,
            "plugin_id": plugin_id,
            "lease": {
                "plugin_id": lease.plugin_id,
                "install_key": lease.install_key,
                "baseline_sha": lease.baseline_sha,
                "expires_at": lease.expires_at,
                "ttl_seconds": LEASE_TTL_SECONDS,
            },
        }

    async def stop(self, studio_id: str, workspace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        async with self._lock:
            entry = self._entries.pop(studio_id, None)
        if entry is not None and entry.task is not None and not entry.task.done():
            entry.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await entry.task

        live = getattr(self._app.state, "sidecar_runtime", None)
        if live is not None:
            plugin_id = entry.plugin_id if entry is not None else (workspace or {}).get("plugin_id")
            if plugin_id:
                released = dev_lease.store_for(live.state_dir).revoke_plugin(str(plugin_id))
                if released:
                    dev_stream.stream_for(live.state_dir).publish(str(plugin_id), "lease_released", {"studio_id": studio_id})
                    inspector_telemetry.telemetry_for(live.state_dir).notify(str(plugin_id))
            if workspace is not None:
                with contextlib.suppress(Exception):
                    store.update_workspace(live.state_dir, studio_id, lambda row: {**row, "dev_active": False})
        return {"active": False}

    async def shutdown(self) -> None:
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            if entry.task is not None and not entry.task.done():
                entry.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await entry.task

    async def _handle_missing_folder(self, state_dir: Path, entry: _DevWatchEntry) -> None:
        entry.last_status = "stopped"
        entry.last_error = {
            "code": "studio_workspace_folder_missing",
            "detail": "Workspace folder no longer exists.",
        }
        released = dev_lease.store_for(state_dir).revoke_plugin(entry.plugin_id)
        if released:
            dev_stream.stream_for(state_dir).publish(
                entry.plugin_id,
                "lease_released",
                {"studio_id": entry.studio_id, "reason": "folder_missing"},
            )
            inspector_telemetry.telemetry_for(state_dir).notify(entry.plugin_id)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(
                store.update_workspace,
                state_dir,
                entry.studio_id,
                lambda row: {**row, "dev_active": False},
            )
        with contextlib.suppress(Exception):
            await asyncio.to_thread(resource_push.notify, "cplugs")
        logger.info("studio_dev_watch_folder_missing", studio_id=entry.studio_id, plugin_id=entry.plugin_id)

    async def _watch_loop(
        self,
        entry: _DevWatchEntry,
        initial_snap: Optional[Dict[str, Tuple[int, int]]] = None,
    ) -> None:
        last_snap = initial_snap
        pending_since: Optional[float] = None
        last_renew = time.monotonic()
        try:
            if last_snap is None:
                try:
                    last_snap = await asyncio.to_thread(dev_runner.snapshot_tree, entry.folder)
                except OSError as exc:
                    logger.warning(
                        "studio_dev_watch_initial_snap_failed",
                        studio_id=entry.studio_id,
                        plugin_id=entry.plugin_id,
                        error_type=type(exc).__name__,
                    )
                    last_snap = {}
            while True:
                await asyncio.sleep(DEBOUNCE_SECONDS)
                live = getattr(self._app.state, "sidecar_runtime", None)
                if live is None:
                    return
                if not entry.folder.exists() or not entry.folder.is_dir():
                    await self._handle_missing_folder(live.state_dir, entry)
                    return
                now = time.monotonic()
                try:
                    if now - last_renew >= RENEW_INTERVAL_SECONDS:
                        last_renew = now
                        dev_lease.store_for(live.state_dir).renew(entry.plugin_id, ttl=LEASE_TTL_SECONDS)
                    cur = await asyncio.to_thread(dev_runner.snapshot_tree, entry.folder)
                except OSError as exc:
                    if not entry.folder.exists() or not entry.folder.is_dir():
                        await self._handle_missing_folder(live.state_dir, entry)
                        return
                    logger.warning(
                        "studio_dev_watch_poll_failed",
                        studio_id=entry.studio_id,
                        plugin_id=entry.plugin_id,
                        error_type=type(exc).__name__,
                    )
                    entry.last_status = "error"
                    entry.last_error = {"code": type(exc).__name__, "detail": str(exc)[:200]}
                    continue
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "studio_dev_watch_poll_failed",
                        studio_id=entry.studio_id,
                        plugin_id=entry.plugin_id,
                        error_type=type(exc).__name__,
                        exc_info=True,
                    )
                    entry.last_status = "error"
                    entry.last_error = {"code": type(exc).__name__, "detail": str(exc)[:200]}
                    continue
                if cur != last_snap:
                    last_snap = cur
                    pending_since = now
                    continue
                if pending_since is not None and (now - pending_since) >= DEBOUNCE_SECONDS:
                    pending_since = None
                    try:
                        res = await self.reload_once(entry.studio_id, entry.plugin_id, entry.folder)
                        if res.get("status") == "permission_widened":
                            with contextlib.suppress(Exception):
                                await asyncio.to_thread(
                                    store.update_workspace,
                                    live.state_dir,
                                    entry.studio_id,
                                    lambda row: {**row, "dev_active": False},
                                )
                            return
                    except StudioActionError as exc:
                        entry.last_status = "error"
                        entry.last_error = {"code": exc.code, "detail": exc.detail}
                    except Exception as exc:  # noqa: BLE001
                        logger.error("studio_dev_watch_reload_failed", studio_id=entry.studio_id, plugin_id=entry.plugin_id, error_type=type(exc).__name__, exc_info=True)
                        entry.last_status = "error"
                        entry.last_error = {"code": type(exc).__name__, "detail": str(exc)[:200]}
        except asyncio.CancelledError:
            raise

    async def reload_once(self, studio_id: str, plugin_id: str, folder: Path) -> Dict[str, Any]:
        t0 = time.perf_counter()
        live, host = self._runtime_and_host()
        state_dir = live.state_dir
        stream = dev_stream.stream_for(state_dir)
        async with dev_routes.reload_lock(state_dir, plugin_id):
            existing = runtime.find(plugin_id)
            if not isinstance(existing, SidecarDefinition) or existing.manifest.tier != sideload.TIER_LOCAL:
                raise StudioActionError(404, "cplug_unknown", f"Local plugin {plugin_id} is not installed.")
            install_key = await asyncio.to_thread(host.install_key, plugin_id)
            try:
                staging, files, manifest = await asyncio.to_thread(sideload.stage, state_dir, plugin_id, folder, dev=True)
            except sideload.SideloadRefused as exc:
                stream.publish(plugin_id, "reload_error", {"code": exc.code, "detail": str(exc)})
                raise StudioActionError(exc.status, exc.code, str(exc)) from exc

            digest = manifest.code_digest
            leases = dev_lease.store_for(state_dir)
            ok, reason, widened = leases.check_reload(plugin_id, install_key, folder, manifest)
            if not ok:
                if reason == "permission_widened":
                    await live.supervisor.disable(plugin_id, "sideload", stop_timeout=0.05)
                    staged = {"name": plugin_id, "digest": digest, "staging": staging, "files": files, "manifest": manifest}
                    await asyncio.to_thread(sideload_routes._commit_blocking, state_dir, folder, staged)
                    await asyncio.to_thread(owner_state.strip_consent, state_dir, plugin_id)
                    await asyncio.to_thread(live.reload_one, plugin_id, item_id=existing.item_id, immediate_ui=True)
                    stream.publish(plugin_id, "permission_widened", {"reason": reason, "widened": widened})
                    entry = self._entries.get(studio_id)
                    if entry is not None:
                        entry.last_status = "permission_widened"
                        entry.last_error = {"code": reason, "widened": widened}
                    await asyncio.to_thread(resource_push.notify, "cplugs")
                    return {"id": plugin_id, "status": "permission_widened", "widened": widened}
                shutil.rmtree(staging, ignore_errors=True)
                raise WorkspaceConflictError(f"Dev trust lease refused reload ({reason}).", code=reason or "lease_required")

            if sideload.unchanged(state_dir, plugin_id, digest):
                shutil.rmtree(staging, ignore_errors=True)
                entry = self._entries.get(studio_id)
                if entry is not None and (entry.last_status == "error" or entry.last_error is not None):
                    entry.last_error = None
                    entry.last_status = "reloaded" if entry.reload_count > 0 else "active"
                    payload = {
                        "id": plugin_id,
                        "status": entry.last_status,
                        "digest": digest,
                        "changed": [],
                        "recovered": True,
                        "timings": {"total_ms": round((time.perf_counter() - t0) * 1000.0, 2)},
                    }
                    stream.publish(plugin_id, "reloaded", payload)
                    inspector_telemetry.telemetry_for(state_dir).notify(plugin_id)
                    await asyncio.to_thread(resource_push.notify, "cplugs")
                return {"id": plugin_id, "status": "unchanged", "digest": digest}

            old_proc = live.supervisor.process(plugin_id)
            await live.supervisor.disable(plugin_id, "restart", stop_timeout=0.05)
            dev_routes._record_stderr(stream, plugin_id, old_proc)
            staged = {"name": plugin_id, "digest": digest, "staging": staging, "files": files, "manifest": manifest}
            try:
                changed = await asyncio.to_thread(sideload_routes._commit_blocking, state_dir, folder, staged)
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
                logger.error("studio_dev_reload_commit_failed", studio_id=studio_id, plugin_id=plugin_id, error_type=type(exc).__name__, exc_info=True)
                raise StudioActionError(500, "sideload_failed", "Dev reload commit failed.") from exc

            proc_state = "tier0"
            ui_error: Optional[Dict[str, str]] = None
            if defn is not None and not defn.manifest.tier0:
                proc_state = await live.supervisor.enable(host.sidecar_spec(defn))
                proc = live.supervisor.process(plugin_id)
                dev_routes._record_stderr(stream, plugin_id, proc)
                if proc is not None and proc_state == "running":
                    ui_error = await dev_routes._probe_dev_ui(proc, defn, stream)

            total_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            payload = {
                "id": plugin_id,
                "status": "reloaded",
                "digest": digest,
                "changed": changed,
                "process": proc_state,
                "ui_error": ui_error,
                "timings": {"total_ms": total_ms},
            }
            entry = self._entries.get(studio_id)
            if entry is not None:
                entry.last_reload_ms = total_ms
                entry.last_status = "reloaded"
                entry.last_error = ui_error
                entry.reload_count += 1
            stream.publish(plugin_id, "reloaded", payload)
            inspector_telemetry.telemetry_for(state_dir).notify(plugin_id)
            await asyncio.to_thread(resource_push.notify, "cplugs")
            return payload

    async def get_inspector_snapshot(self, studio_id: str, workspace: Dict[str, Any]) -> Dict[str, Any]:
        live = getattr(self._app.state, "sidecar_runtime", None)
        dev_status = self.status_for(studio_id, live.state_dir if live else None, str(workspace["plugin_id"]))
        return await inspector_preview.get_inspector_snapshot(self._app, studio_id, workspace, dev_status)

    async def preview_render(
        self,
        studio_id: str,
        workspace: Dict[str, Any],
        *,
        theme_id: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        surface_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await inspector_preview.preview_render(
            self._app,
            studio_id,
            workspace,
            theme_id=theme_id,
            width=width,
            height=height,
            surface_id=surface_id,
        )


def manager_for(app: Any) -> DevSessionManager:
    mgr = getattr(app.state, "plugin_studio_dev", None)
    if mgr is None:
        mgr = DevSessionManager(app)
        app.state.plugin_studio_dev = mgr
    return mgr
