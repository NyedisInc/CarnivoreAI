
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException

from src.core.catalog import publish_facts, publish_github, publish_prepare_kinds
from src.core.plugin_studio import dev_session
from src.core.plugin_studio.errors import StudioActionError, WorkspaceConflictError, WorkspaceValidationError
from src.core import resource_push
from src.models.catalog_publish import OwnerPublishRequest
from src.plugins.cli import tester
from src.plugins.host import (
    dev_routes,
    developer_mode,
    owner_switch,
    runtime,
    sideload,
    sideload_routes,
    state as owner_state,
)
from src.plugins.host.sidecar_registry import SidecarDefinition


async def test_in_sandbox(
    folder: Path,
    *,
    unit_only: bool = False,
    smoke_only: bool = False,
) -> Dict[str, Any]:
    rep = await asyncio.to_thread(
        tester.test_folder,
        folder,
        unit_only=unit_only,
        smoke_only=smoke_only,
    )
    check_ok = not any("carnivore.toml" in e or "manifest" in e.lower() for e in rep.errors)
    return {
        "ok": rep.ok,
        "check": {"ok": check_ok, "warnings": rep.warnings},
        "unit": {"output": rep.unit_output},
        "smoke": rep.smoke_summary,
        "errors": rep.errors,
        "warnings": rep.warnings,
    }


async def install_workspace(
    app: Any,
    folder: Path,
    *,
    activate_runtime: bool = True,
    auto_approve: bool = True,
) -> Dict[str, Any]:
    if not developer_mode.is_on():
        raise WorkspaceConflictError(
            "Developer mode is off; enable Developer Mode in settings to install a local Studio plugin.",
            code="developer_mode_off",
        )
    live = getattr(app.state, "sidecar_runtime", None)
    host = runtime.host_for(app)
    if live is None or host is None:
        raise StudioActionError(503, "cplug_runtime_unavailable", "The plugin runtime is not running.")

    state_dir = live.state_dir
    if not sideload.allowed(state_dir, sideload.wall):
        if auto_approve and developer_mode.is_on():
            await asyncio.to_thread(sideload.set_switch, state_dir, True)
        else:
            raise WorkspaceConflictError("Sideload switch is off.", code="sideload_off")

    source_check = folder if folder.is_symlink() else Path(os.path.realpath(folder))
    try:
        plugin_name = await asyncio.to_thread(sideload_routes.name_of, source_check, None)
    except sideload.SideloadRefused as exc:
        raise dev_session._studio_err_from_http(sideload_routes._refuse(exc), "sideload_failed") from exc

    async with dev_routes.reload_lock(state_dir, plugin_name):
        try:
            sync_res = await sideload_routes.sync_folder(live, folder, None, _lock_held=True)
        except HTTPException as exc:
            raise dev_session._studio_err_from_http(exc, "sideload_failed") from exc

        plugin_id = str(sync_res["id"])
        defn = runtime.find(plugin_id)
        if not isinstance(defn, SidecarDefinition):
            raise StudioActionError(404, "cplug_unknown", f"Local plugin {plugin_id} could not be loaded.")

        before_enabled = await asyncio.to_thread(host.enabled, plugin_id)
        await asyncio.to_thread(
            dev_session._consent_and_enable_blocking,
            state_dir,
            defn.manifest,
            auto_approve=auto_approve,
        )

        if activate_runtime:
            if not await asyncio.to_thread(owner_switch.read, state_dir):
                await asyncio.to_thread(owner_switch.write, state_dir, True)
            if not await live.set_switch(True):
                raise WorkspaceConflictError(
                    "Runtime safe mode is forced by environment and cannot be activated.",
                    code="safe_mode_forced",
                )

        if not before_enabled:
            await host.switched(plugin_id, True)
        else:
            await host.restart_sidecar(defn)

        st_after = await asyncio.to_thread(owner_state.get, state_dir, defn.manifest)
    await asyncio.to_thread(resource_push.notify, "cplugs")
    runtime_active = not any(live.safe_mode().values()) if hasattr(live, "safe_mode") else True
    return {
        "ok": True,
        "plugin_id": plugin_id,
        "item_id": sync_res.get("item_id", f"local/{plugin_id}"),
        "enabled": bool(st_after.enabled),
        "runtime_active": bool(runtime_active),
        "digest": defn.manifest.code_digest,
    }


def build_publish_request(
    workspace: Dict[str, Any],
    *,
    mode: str = "local",
    repo: Optional[str] = None,
    tag: Optional[str] = None,
    pointer: Optional[str] = None,
    commit_sha: Optional[str] = None,
    subdir: Optional[str] = None,
    version: Optional[str] = None,
    digest: Optional[str] = None,
    dry_run: bool = True,
    include_workspace_files: bool = False,
) -> OwnerPublishRequest:
    clean_mode = (mode or "local").strip().lower()
    if clean_mode not in ("local", "github"):
        raise WorkspaceValidationError("publish mode must be 'local' or 'github'", code="invalid_publish_mode")
    folder = str(workspace["folder"])
    plugin_id = str(workspace["plugin_id"])
    eff_version = version or publish_facts.declared_version(publish_prepare_kinds.KIND_CPLUG, folder) or "0.1.0"
    clean_digest = digest.strip() if isinstance(digest, str) and digest.strip() else None

    if clean_mode == "github":
        try:
            prepared_gh = publish_github.prepare_github_publish(
                pointer=pointer,
                repo=repo,
                tag=tag,
                commit_sha=commit_sha,
                subdir=subdir,
                kind=publish_prepare_kinds.KIND_CPLUG,
                name=plugin_id,
                version=eff_version,
                default_kind=publish_prepare_kinds.KIND_CPLUG,
            )
        except HTTPException as exc:
            raise dev_session._studio_err_from_http(exc, "invalid_github_pointer") from exc
        return OwnerPublishRequest(
            source_type="github",
            path=folder if include_workspace_files else None,
            pointer=prepared_gh.pointer,
            repo=None,
            tag=None,
            commit_sha=prepared_gh.commit_sha or None,
            subdir=prepared_gh.subdir or None,
            kind=publish_prepare_kinds.KIND_CPLUG,
            name=plugin_id,
            version=eff_version,
            digest=clean_digest or (None if include_workspace_files else prepared_gh.digest),
            dry_run=dry_run,
        )

    return OwnerPublishRequest(
        source_type="upload",
        path=folder,
        kind=publish_prepare_kinds.KIND_CPLUG,
        name=plugin_id,
        version=eff_version,
        digest=clean_digest,
        dry_run=dry_run,
    )
