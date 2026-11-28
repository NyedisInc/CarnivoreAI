
from __future__ import annotations

import asyncio
import shutil
import sqlite3
from dataclasses import replace
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from src.api.auth import require_auth
from src.core.resource_push import topics
from src.core.skills import kinds
from src.core.skills.install_types import PROJECT_PATH_INVALID
from src.core.skills.ledger_types import SCOPE_GLOBAL, SCOPE_PROJECT
from src.core.skills.project_scope import ProjectPathRefused, resolve_project_path
from src.plugins.host import (
    consent as consent_mod,
    github_install_support as support,
    identity,
    inspector_telemetry,
    owner_switch,
    runtime,
    sidecar_registry,
    sideload,
    sideload_git,
    sideload_kind,
    sideload_other,
    sideload_routes,
    state as owner_state,
)
from src.plugins.host.owner_switch import _runtime as _sidecar_runtime
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.plugins.sdk.permission_registry import risk_of

logger = structlog.get_logger()

router = APIRouter(
    prefix="/cplug-owner",
    tags=["cplugs"],
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)

_ONE_AT_A_TIME = asyncio.Lock()


class GithubPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: StrictStr
    ref: Optional[StrictStr] = None
    subdir: Optional[StrictStr] = None
    scope: Optional[Literal["global", "project"]] = None
    project_path: Optional[StrictStr] = None


class GithubInstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: StrictStr
    ref: Optional[StrictStr] = None
    subdir: Optional[StrictStr] = None
    name: Optional[StrictStr] = None
    scope: Optional[Literal["global", "project"]] = None
    project_path: Optional[StrictStr] = None
    enable: StrictBool = True
    activate_runtime: StrictBool = False
    secrets: Optional[Dict[StrictStr, StrictStr]] = None
    consent: Optional[Dict[str, Any]] = None
    ui_slots: Optional[List[StrictStr]] = None


async def _resolve_scope(
    request: Request,
    kind: str,
    scope: Optional[str],
    project_path: Optional[str],
) -> Tuple[str, Optional[str]]:
    if kind == kinds.KIND_CPLUG:
        if scope == SCOPE_PROJECT or project_path:
            raise support.err(409, "scope_unsupported", "app-wide cplugs only support global scope")
        return SCOPE_GLOBAL, None
    effective = scope or SCOPE_GLOBAL
    if effective == SCOPE_GLOBAL:
        if project_path:
            raise HTTPException(status_code=400, detail="a global install takes no project_path")
        return SCOPE_GLOBAL, None
    if not project_path or not project_path.strip():
        raise HTTPException(status_code=400, detail="a project install requires a project_path")
    services = getattr(request.app.state, "services", None)
    roots = getattr(services, "install_roots", None)
    state_dir = services.settings_reader.state_dir() if getattr(services, "settings_reader", None) else runtime.host_for(request.app).state_dir
    try:
        resolved = await asyncio.to_thread(resolve_project_path, project_path, roots=roots, state_dir=state_dir)
    except ProjectPathRefused as exc:
        raise support.err(409, PROJECT_PATH_INVALID, exc.detail) from exc
    return SCOPE_PROJECT, resolved


@router.post("/github/preview")
async def post_github_preview(body: GithubPreviewBody, request: Request) -> Dict[str, Any]:
    """Validate and clone a GitHub repository into scratch space to inspect manifest, gates, secrets, and consent sheet."""
    try:
        _owner, _repo, canonical_url, ref = sideload_git.parse_github_source(body.source, body.ref)
        parts = sideload_git.check_subdir(body.subdir)
    except sideload.SideloadRefused as exc:
        raise sideload_routes._refuse(exc) from exc

    runtime.host_for(request.app)
    live = _sidecar_runtime(request)
    state_dir = live.state_dir
    support.check_revoked_github_install(request, f"{_owner}/{_repo}")
    catalog_items = support.catalog_items_from_app(request)

    async with _ONE_AT_A_TIME:
        try:
            checkout, source_dir, commit = await asyncio.to_thread(
                support.clone_for_preview_or_install, state_dir, canonical_url, ref, parts
            )
        except sideload.SideloadRefused as exc:
            raise sideload_routes._refuse(exc) from exc
        try:
            kind = await asyncio.to_thread(sideload_kind.detect, source_dir)
            scope, project_path = await _resolve_scope(request, kind, body.scope, body.project_path)
            if kind == kinds.KIND_CPLUG:
                staged_info = await asyncio.to_thread(
                    support.preview_cplug_blocking,
                    state_dir,
                    source_dir,
                    canonical_url,
                    runtime.reserved_plugin_ids(),
                    runtime.renamed_ids(),
                    catalog_items,
                )
                try:
                    m = staged_info["manifest"]
                    support.check_revoked_github_install(
                        request,
                        f"{_owner}/{_repo}",
                        name=staged_info["name"],
                        raw_id=getattr(m, "id", None),
                    )
                    sheet = consent_mod.sheet(m)
                    secrets_meta = [
                        {"name": s.name, "label": s.label, "hosts": list(m.network.secret_hosts(s.name))}
                        for s in m.network.secrets
                    ]
                    declared_slots = consent_mod.declared_ui_slots(m)
                    slot_meta = {
                        "ui_slots": list(getattr(m, "ui_slots", ()) or ()),
                        "ui_contribute": {str(k): list(v) for k, v in (getattr(m, "ui_contribute", None) or {}).items()},
                        "services": {
                            "provides": [dict(x) for x in (getattr(m, "services_provides", ()) or ()) if isinstance(x, Mapping)],
                            "consumes": list(getattr(m, "services_consumes", ()) or ()),
                        },
                        "events": {
                            "on": list(getattr(m, "events_on", ()) or ()),
                            "emit": list(getattr(m, "events_emit", ()) or ()),
                            "allowed": list(getattr(m, "events_allowed", ()) or ()),
                        },
                        "declared_ui_slots": list(declared_slots),
                    }
                    return {
                        "id": staged_info["name"],
                        "item_id": f"{identity.GITHUB_PUBLISHER}/{staged_info['name']}",
                        "name": m.name or staged_info["name"],
                        "description": m.description,
                        "version": m.version,
                        "kind": "cplug",
                        "trust_tier": "unverified_github",
                        "trust_badge": "Unverified GitHub Repo",
                        "unverified": True,
                        "code_sha256": m.code_digest,
                        "permissions": sheet["permissions"],
                        "risks": {p: risk_of(p, m.tier) for p in m.permissions},
                        "warnings": sheet["warnings"],
                        "consent_sheet": sheet,
                        "secrets": secrets_meta,
                        "scope": scope,
                        "supported_scopes": [SCOPE_GLOBAL],
                        "project_path": None,
                        "runtime_active": not any(live.safe_mode().values()),
                        "source": {"owner": _owner, "repo": _repo, "url": canonical_url, "ref": ref, "commit": commit, "subdir": body.subdir or ""},
                        **slot_meta,
                    }
                finally:
                    shutil.rmtree(staged_info["staging"], ignore_errors=True)
            if kind == kinds.KIND_PLUGIN:
                env = sideload_routes.env_of(request, state_dir)
                if env is None:
                    raise support.err(503, "install_roots_unavailable", "the app has no agent-plugin install folders")
                name = await asyncio.to_thread(sideload_kind.name_for, kind, source_dir, None)
                raw_id = (sideload_kind._read_json(source_dir / ".claude-plugin" / "plugin.json") or {}).get("name")
                support.check_revoked_github_install(
                    request,
                    f"{_owner}/{_repo}",
                    name=name,
                    raw_id=raw_id if isinstance(raw_id, str) else None,
                )
                support.check_hijack(
                    state_dir,
                    name,
                    raw_id if isinstance(raw_id, str) else None,
                    canonical_url,
                    (),
                    (),
                    catalog_items,
                    kind=kinds.KIND_PLUGIN,
                )
                staged, _files = await asyncio.to_thread(sideload_other._stage, env.roots, source_dir)
                try:
                    refusal = await asyncio.to_thread(sideload_other.check_manifest, kind, staged, expected_id=name)
                    if refusal is not None:
                        raise support.err(422, "manifest_invalid", refusal)
                    digest, _entries = await asyncio.to_thread(sideload_other.tree_digest, staged)
                    body_sha = await asyncio.to_thread(sideload_other._body_sha, staged, kind)
                    return support.agent_plugin_payload(
                        name, staged, digest, body_sha, scope, project_path, canonical_url, ref, commit, body.subdir or "",
                    )
                finally:
                    shutil.rmtree(staged.parent, ignore_errors=True)
            raise support.err(422, "kind_unsupported", f"direct GitHub preview currently supports cplug and agent-plugin repositories (got {kind})")
        except sideload.SideloadRefused as exc:
            raise sideload_routes._refuse(exc) from exc
        finally:
            await asyncio.to_thread(shutil.rmtree, checkout, True)


@router.post("/github/install")
async def post_github_install(body: GithubInstallBody, request: Request) -> Dict[str, Any]:
    """Install an unverified GitHub repo plugin outside Developer Mode with explicit consent, inline secrets, and optional runtime activation."""
    try:
        _owner, _repo, canonical_url, ref = sideload_git.parse_github_source(body.source, body.ref)
        parts = sideload_git.check_subdir(body.subdir)
    except sideload.SideloadRefused as exc:
        raise sideload_routes._refuse(exc) from exc

    host = runtime.host_for(request.app)
    live = _sidecar_runtime(request)
    state_dir = live.state_dir
    support.check_revoked_github_install(request, f"{_owner}/{_repo}")
    catalog_items = support.catalog_items_from_app(request)

    if body.enable and body.activate_runtime and live._env_safe():
        raise support.err(409, "safe_mode_forced", "runtime safe mode is forced by environment and cannot be activated")

    async with _ONE_AT_A_TIME:
        try:
            checkout, source_dir, commit = await asyncio.to_thread(
                support.clone_for_preview_or_install, state_dir, canonical_url, ref, parts
            )
        except sideload.SideloadRefused as exc:
            raise sideload_routes._refuse(exc) from exc
        adopted = False
        try:
            kind = await asyncio.to_thread(sideload_kind.detect, source_dir)
            scope, project_path = await _resolve_scope(request, kind, body.scope, body.project_path)
            if kind == kinds.KIND_CPLUG:
                staged_info = await asyncio.to_thread(
                    support.preview_cplug_blocking,
                    state_dir,
                    source_dir,
                    canonical_url,
                    runtime.reserved_plugin_ids(),
                    runtime.renamed_ids(),
                    catalog_items,
                    body.name,
                )
                name = staged_info["name"]
                staging = staged_info["staging"]
                manifest_gh = staged_info["manifest"]
                tx: Optional[support.GithubCommitTx] = None
                reloaded = False
                from src.plugins.host import dev_routes  # noqa: PLC0415

                async with dev_routes.reload_lock(state_dir, name):
                    try:
                        support.check_revoked_github_install(
                            request,
                            f"{_owner}/{_repo}",
                            name=name,
                            raw_id=getattr(manifest_gh, "id", None),
                        )
                        declared_slots = consent_mod.declared_ui_slots(manifest_gh)
                        if body.ui_slots is not None:
                            extra_slots = sorted(set(body.ui_slots) - set(declared_slots))
                            if extra_slots:
                                raise support.err(422, "grant_not_asked", f"{name} does not ask for ui slots {', '.join(extra_slots)}")
                        wanted_slots = (
                            tuple(s for s in declared_slots if s in body.ui_slots)
                            if body.ui_slots is not None
                            else declared_slots
                        )
                        need_slot_check = bool(
                            declared_slots
                            or body.ui_slots is not None
                            or (isinstance(body.consent, Mapping) and "ui_slots_sha" in body.consent)
                        )
                        try:
                            if body.enable:
                                consent_mod.check(
                                    manifest_gh,
                                    list(manifest_gh.permissions),
                                    (),
                                    body.consent,
                                    requested_slots=wanted_slots if need_slot_check else None,
                                    current_slots=(),
                                )
                        except consent_mod.ConsentRefused as exc:
                            raise support.err(exc.status, exc.code, str(exc)) from exc
                        support.validate_inline_secrets(manifest_gh, body.secrets)
                        if live.supervisor.process(name) is not None or live.supervisor.state(name) != "unknown":
                            await live.supervisor.disable(name, "sideload", stop_timeout=0.05)
                        tx = await asyncio.to_thread(
                            support.commit_cplug_github_tx,
                            state_dir,
                            name,
                            staging,
                            staged_info["files"],
                            manifest_gh,
                            canonical_url,
                            source_dir,
                            checkout,
                            commit_sha=commit,
                            repo_slug=f"{_owner}/{_repo}",
                        )
                        install_key = tx.install_key
                        adopted = True
                        secrets_status, sec_snap = await asyncio.to_thread(
                            support.store_inline_secrets_tx, state_dir, install_key, manifest_gh, body.secrets
                        )
                        tx.secrets_snapshot = sec_snap
                        git_entry = await asyncio.to_thread(sideload_git.record, state_dir, name, canonical_url, ref, parts, commit)
                        await asyncio.to_thread(
                            owner_state.update,
                            state_dir,
                            manifest_gh,
                            None,
                            lambda st: replace(
                                st,
                                enabled=bool(body.enable),
                                grants=tuple(manifest_gh.permissions) if body.enable else (),
                                ui_slot_grants=wanted_slots if body.enable else (),
                                digest=manifest_gh.code_digest if body.enable else "",
                            ),
                        )
                        if body.enable and body.activate_runtime:
                            await asyncio.to_thread(owner_switch.write, state_dir, True)
                            ok = await live.set_switch(True)
                            if not ok:
                                raise support.err(409, "safe_mode_forced", "runtime safe mode is forced and could not be activated")
                        defn = await asyncio.to_thread(live.reload_one, name, item_id=f"{identity.GITHUB_PUBLISHER}/{name}", immediate_ui=True)
                        reloaded = True
                        if defn is not None and body.enable:
                            await host._switch_sidecar(defn, True)
                        await asyncio.to_thread(tx.finalize)
                        host.publish(runtime.CPLUGS_TOPIC)
                        if declared_slots or getattr(manifest_gh, "ui_slots", ()):
                            host.publish(topics.CPLUG_SLOTS)
                        inspector_telemetry.telemetry_for(state_dir).notify(name, install_key)
                        logger.info("cplug_github_installed", cplug=name, commit=commit[:12], enabled=bool(body.enable), activate_runtime=bool(body.enable and body.activate_runtime))
                        return {
                            "id": name,
                            "item_id": f"{identity.GITHUB_PUBLISHER}/{name}",
                            "install_key": install_key,
                            "kind": "cplug",
                            "trust_tier": "unverified_github",
                            "trust_badge": "Unverified GitHub Repo",
                            "unverified": True,
                            "code_sha256": manifest_gh.code_digest,
                            "scope": SCOPE_GLOBAL,
                            "supported_scopes": [SCOPE_GLOBAL],
                            "enabled": bool(body.enable),
                            "runtime_active": not any(live.safe_mode().values()),
                            "secrets_status": secrets_status,
                            "git": git_entry,
                        }
                    except BaseException:
                        if tx is not None:
                            await asyncio.to_thread(tx.rollback)
                            adopted = False
                        if reloaded:
                            try:
                                await asyncio.to_thread(live.reload_one, name, item_id=f"{identity.GITHUB_PUBLISHER}/{name}")
                            except Exception:
                                sidecar_registry.unload(name)
                        shutil.rmtree(staging, ignore_errors=True)
                        raise
            if kind == kinds.KIND_PLUGIN:
                env = sideload_routes.env_of(request, state_dir)
                if env is None:
                    raise support.err(503, "install_roots_unavailable", "the app has no agent-plugin install folders")
                name = await asyncio.to_thread(sideload_kind.name_for, kind, source_dir, body.name)
                raw_id = (sideload_kind._read_json(source_dir / ".claude-plugin" / "plugin.json") or {}).get("name")
                support.check_revoked_github_install(
                    request,
                    f"{_owner}/{_repo}",
                    name=name,
                    raw_id=raw_id if isinstance(raw_id, str) else None,
                )
                support.check_hijack(
                    state_dir,
                    name,
                    raw_id if isinstance(raw_id, str) else None,
                    canonical_url,
                    (),
                    (),
                    catalog_items,
                    kind=kinds.KIND_PLUGIN,
                )
                result = await asyncio.to_thread(
                    support.install_agent_plugin_blocking,
                    state_dir,
                    env,
                    source_dir,
                    name,
                    scope,
                    project_path,
                    canonical_url,
                    body.consent,
                    commit_sha=commit,
                    repo_slug=f"{_owner}/{_repo}",
                )
                host.publish(runtime.CPLUGS_TOPIC)
                return {**result, "runtime_active": not any(live.safe_mode().values())}
            raise support.err(422, "kind_unsupported", f"direct GitHub install supports cplug and agent-plugin repositories (got {kind})")
        except sideload.SideloadRefused as exc:
            raise sideload_routes._refuse(exc) from exc
        except sqlite3.Error as exc:
            logger.warning("cplug_github_ledger_error", error_type=type(exc).__name__)
            raise support.err(500, "ledger_error", "install ledger write failed") from exc
        finally:
            if not adopted:
                await asyncio.to_thread(shutil.rmtree, checkout, True)
