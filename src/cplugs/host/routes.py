
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from starlette.routing import Match
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt

from src.cplugs.host import (activity_log, consent as consent_mod, dependencies, destination_check, gate, identity, net_routes, owner_switch, sideload, sideload_routes, purge_guard, purge_kept, purge_owned, purge_removed,
                             risk, runtime, state as owner_state, system_lifecycle)
from src.cplugs.host import sidecar_routes, sidecar_ui, sidecar_view
from src.cplugs.host.sidecar_registry import SidecarDefinition
from src.cplugs.sdk import permission_registry as registry, settings_aliases
from src.cplugs.sdk.definition import CplugDefinition, SettingsVerdict, as_warning
from src.cplugs.sdk.manifest import ID_PATTERN
from src.api.auth import require_auth
from src.core.item_settings_schema import check_key, parse_schema

logger = structlog.get_logger()

_SECRET_KEY = re.compile(r"(token|secret|password|passwd|api_?key|credential)", re.IGNORECASE)


class GrantsBody(BaseModel):
    """The app permissions to grant (the whole set; absent ones are revoked)."""

    model_config = ConfigDict(extra="forbid")
    app: List[str]


class ConsentBody(BaseModel):

    model_config = ConfigDict(extra="forbid")
    digest: str
    body_sha: str
    grants_sha: str
    ticks: List[str] = []


class UpdateBody(BaseModel):
    """An owner change; ``revision`` is the one the caller read."""

    model_config = ConfigDict(extra="forbid")
    revision: StrictInt
    enabled: Optional[StrictBool] = None
    grants: Optional[GrantsBody] = None
    settings: Optional[Dict[str, Any]] = None
    consent: Optional[ConsentBody] = None
    confirm_dependents: Optional[StrictBool] = None


class PurgeBody(BaseModel):
    """A purge: price first (``dry_run``), then confirm with the token the price answered."""

    model_config = ConfigDict(extra="forbid")
    dry_run: StrictBool = True
    confirm_token: Optional[str] = None


host_router = APIRouter(prefix="/cplugs", tags=["cplugs"], dependencies=[Depends(require_auth)])


host_router.include_router(net_routes.router)
host_router.include_router(owner_switch.safe_mode_router)


def _error(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail, **extra})


def _install_key(host: runtime.Host, cplug_id: str) -> Optional[str]:
    try:
        return host.install_key(cplug_id)
    except identity.LedgerUnreadable:
        return None


def cplug_row(host: runtime.Host, d: CplugDefinition) -> Dict[str, Any]:
    m = d.manifest
    st = owner_state.get(host.state_dir, m)
    needs = [p for p in m.permissions if p not in st.grants]
    consent_required = risk.needs_consent(m.tier)
    if consent_required and st.grants and st.digest != m.code_digest:
        needs = list(m.permissions)
    blocked = list(gate.blocked_by(m.id, host.state_dir))
    sidecar = isinstance(d, SidecarDefinition)
    live = host.sidecar_runtime() if sidecar else None
    process = live.supervisor.state(d.id) if live is not None else None
    detail = host.unavailable.get(d.id)
    if not st.enabled:
        status = "disabled"
    elif d.id in host.unavailable:
        status = "unavailable"
    elif sidecar and live is not None and process not in ("running", "idle") and not (needs and process == "disabled"):
        status, detail = "unavailable", process
    elif needs:
        status = "needs_approval"
    elif blocked:
        status = "inert"
    else:
        status = "active"
    return {
        "id": m.id, "name_key": m.name_key, "description_key": m.description_key, "version": m.version,
        "icon": m.icon, "tier": m.tier, "author": m.author, "surfaces": m.surfaces.as_wire(),
        "permissions": {"app": list(m.permissions)}, "grants": {"app": list(st.grants)}, "enabled": st.enabled,
        "risks": {p: registry.risk_of(p, m.tier) for p in m.permissions}, "consent_required": consent_required,
        "reasons": {p: r for p in m.permissions if (r := consent_mod.reason_for(m, p))},
        "warnings": consent_mod.warnings_of(m),
        "state": status, "needs": needs, "detail": detail,
        "runtime": "sidecar" if sidecar else "compiled", "trust": m.tier, "process": process,
        "unverified": sidecar and sideload.is_local(d.item_id),
        "changed_files": sideload.items(host.state_dir).get(d.id, {}).get("changed", []) if sidecar and sideload.is_local(d.item_id) else [],
        "name": m.name if sidecar else None, "description": m.description if sidecar else None,
        "publisher": d.item_id.partition("/")[0] if sidecar else None,
        "tools": ([t["name"] for t in m.tools] if process in ("running", "idle") else []) if sidecar else None,
        "routes": list(m.routes) if sidecar else None,
        "declared_tools": [t["name"] for t in m.tools if isinstance(t, dict)] if sidecar else None,
        "install_key": _install_key(host, d.id) if sidecar else None,
        "views": [{"name": v["name"], "surfaces": v["surfaces"], "fits": v["fits"]} for v in m.views] if sidecar else None,
        "preview": f"/cplugs/{d.id}/preview?rev={m.code_digest[:12]}" if sidecar and m.preview else None,
        "settings": settings_aliases.merged(runtime.settings_defaults(m.settings_schema), st.settings, m.settings_aliases),
        "settings_schema": dict(m.settings_schema),
        "storage_bytes": host.storage(d.id).size_bytes(), "revision": st.revision,
        "requires": list(m.requires), "requires_off": [r for r in m.requires if not host.enabled(r)],
        "blocked_by": blocked,
        "requires_core": list(m.requires_core), "min_app_version": m.min_app_version,
        "dependencies": dependencies.dependency_view(m, host.state_dir),
    }


def _orphans(host: runtime.Host) -> List[Dict[str, Any]]:
    root = host.state_dir / owner_state.STATE_DIR_NAME
    shipped = {d.id for d in runtime.definitions()} | {d.id for d in runtime.listed()}
    if not root.is_dir():
        return []
    rows = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and ID_PATTERN.match(p.name) and p.name not in shipped):
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        rows.append({"id": folder.name, "state": "removed", "enabled": False, "storage_bytes": size})
    try:
        held = [r for r in identity.installs(host.state_dir) if r.name not in shipped]
    except identity.LedgerUnreadable:
        return rows
    for record in held:
        folder = identity.data_dir(host.state_dir, record.uuid)
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.is_dir() else 0
        rows.append({"id": record.name, "state": "removed", "enabled": False, "storage_bytes": size, "runtime": "sidecar"})
    return rows


def _shipped(cplug_id: str) -> CplugDefinition:
    d = runtime.find(cplug_id)
    if d is None or runtime.hidden(d):
        raise _error(404, "cplug_unknown", f"no plugin {cplug_id}")
    return d


def _folded(cplug_id: str, body: Optional["UpdateBody"] = None) -> Tuple[str, Optional["UpdateBody"]]:
    target = None if runtime.find(cplug_id) is not None else runtime.legacy_target(cplug_id)
    if target is None:
        return cplug_id, body
    if body is None:
        return target.id, None
    carried = dict(body.settings or {})
    if body.enabled is not None:
        carried[target.manifest.legacy_ids[cplug_id]] = body.enabled
    return target.id, body.model_copy(update={"enabled": None, "grants": None, "settings": carried or None})


@host_router.get("")
async def list_cplugs(request: Request) -> Dict[str, Any]:
    """Every plugin, shipped then removed. Output: {cplugs}."""
    host = runtime.host_for(request.app)
    rows = await run_in_threadpool(lambda: [cplug_row(host, d) for d in runtime.listed()] + _orphans(host))
    return {"cplugs": rows}


@host_router.get("/{cplug_id}")
async def get_cplug(cplug_id: str, request: Request) -> Dict[str, Any]:
    """One shipped plugin (a retired id answers with the plugin that absorbed it). Output: its row."""
    host = runtime.host_for(request.app)
    return await run_in_threadpool(cplug_row, host, _shipped(_folded(cplug_id)[0]))


@host_router.get("/{cplug_id}/sheet")
async def get_sheet(cplug_id: str, request: Request) -> Dict[str, Any]:
    """The permission sheet to read before enabling or granting (consent.py). Output: the sheet."""
    host = runtime.host_for(request.app)
    d = _shipped(cplug_id)
    shown = await run_in_threadpool(lambda: consent_mod.sheet(d.manifest, owner_state.get(host.state_dir, d.manifest).grants))
    if isinstance(d, SidecarDefinition) and sideload.is_local(d.item_id):
        shown = {**shown, "unverified": True, "changed_files": sideload.items(host.state_dir).get(d.id, {}).get("changed", [])}
    return shown


@host_router.get("/{cplug_id}/activity")
async def get_activity(cplug_id: str, request: Request, limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """The newest capability calls this plugin made (never a query, a line of text or a secret). Output: {activity}."""
    host = runtime.host_for(request.app)
    _shipped(cplug_id)
    try:
        rows = await run_in_threadpool(activity_log.ActivityLog(host.state_dir).recent, host.install_key(cplug_id), limit)
    except (sqlite3.Error, OSError) as exc:
        raise _error(503, "activity_unreadable", "the activity log could not be read") from exc
    return {"activity": rows}


def _check(d: CplugDefinition, body: UpdateBody) -> None:
    m = d.manifest
    if body.enabled is False and m.tier == "core":
        raise _error(422, "core_cannot_disable", f"{m.id} is part of the app")
    if body.grants is not None:
        extra = sorted(set(body.grants.app) - set(m.permissions))
        if extra:
            raise _error(422, "grant_not_asked", f"{m.id} does not ask for {', '.join(extra)}")
    if body.settings is not None:
        schema = parse_schema(m.settings_schema)
        for key, value in settings_aliases.translate(body.settings, m.settings_aliases).items():
            refusal = "setting_secret" if _SECRET_KEY.search(key) else check_key(schema, key, value)
            if refusal:
                raise _error(422, "settings_invalid", f"{key}: {refusal}")
        folder_problem = destination_check.refused(m.data, settings_aliases.translate(body.settings, m.settings_aliases))
        if folder_problem:
            raise _error(422, "destination_refused", folder_problem)


def _own_check(d: CplugDefinition, body: UpdateBody) -> Optional[SettingsVerdict]:
    if body.settings is None or d.settings_check is None:
        return None
    verdict = d.settings_check(settings_aliases.translate(body.settings, d.manifest.settings_aliases))
    if verdict.refusal:
        raise _error(422, "settings_refused", verdict.refusal)
    return verdict


@host_router.put("/{cplug_id}")
async def put_cplug(cplug_id: str, body: UpdateBody, request: Request) -> Dict[str, Any]:
    """Change a plugin's owner state (compare-and-set on ``revision``); a retired id acts on the plugin that absorbed it. Output: its row."""
    host = runtime.host_for(request.app)
    cplug_id, body = _folded(cplug_id, body)
    d = _shipped(cplug_id)
    _check(d, body)
    verdict = await run_in_threadpool(_own_check, d, body)

    def mutate(st: owner_state.CplugState) -> owner_state.CplugState:
        changes: Dict[str, Any] = {}
        if body.enabled is not None:
            changes["enabled"] = body.enabled
        if body.grants is not None:
            changes["grants"] = tuple(p for p in d.manifest.permissions if p in body.grants.app)
        wanted = changes.get("grants", st.grants)
        if risk.needs_consent(d.manifest.tier) and (body.enabled is True or not set(wanted) <= set(st.grants)):
            consent_mod.check(d.manifest, wanted, st.grants, body.consent.model_dump() if body.consent else None)
            changes["digest"] = d.manifest.code_digest
        if body.settings is not None:
            changes["settings"] = {**st.settings, **settings_aliases.translate(body.settings, d.manifest.settings_aliases)}
        return replace(st, **changes)

    before = await run_in_threadpool(host.enabled, cplug_id)
    grants_before = await run_in_threadpool(lambda: owner_state.get(host.state_dir, d.manifest).grants)
    if body.enabled is True and not before:
        blockers = await run_in_threadpool(dependencies.enable_blockers, d.manifest)
        if blockers:
            raise _error(409, "requirements_unmet", f"{cplug_id} cannot be turned on: its requirements are not met", unmet=blockers)
    if body.enabled is False and before and not body.confirm_dependents:
        dependents = await run_in_threadpool(dependencies.enabled_dependents, cplug_id, host.state_dir)
        if dependents:
            raise _error(409, "has_dependents", f"{', '.join(dependents)} need {cplug_id}; send confirm_dependents to turn it off anyway",
                         dependents=dependents)
    try:
        after = await run_in_threadpool(owner_state.update, host.state_dir, d.manifest, body.revision, mutate)
    except owner_state.StaleRevision as exc:
        raise _error(409, "stale_revision", str(exc), current=exc.current.as_wire()) from exc
    except consent_mod.ConsentRefused as exc:
        raise _error(exc.status, exc.code, exc.detail) from exc
    except owner_state.StateWriteFailed as exc:
        raise _error(503, "cplug_state_unwritable", "the plugin state file could not be written") from exc
    if after.enabled != before:
        await host.switched(cplug_id, after.enabled)
    elif after.enabled and isinstance(d, SidecarDefinition) and tuple(after.grants) != tuple(grants_before):
        await host.restart_sidecar(d)
    if body.settings is not None:
        await host.settings_saved(cplug_id)
    logger.info("cplug_state_changed", cplug=cplug_id, enabled=after.enabled, grants=list(after.grants),
                revision=after.revision)
    host.publish(runtime.CPLUGS_TOPIC)
    row = await run_in_threadpool(cplug_row, host, d)
    if body.settings is not None:
        advice = await run_in_threadpool(destination_check.warnings, d.manifest.data,
                                         settings_aliases.translate(body.settings, d.manifest.settings_aliases), host.state_dir)
        advice = [*advice, *(as_warning(w) for w in (verdict.warnings if verdict is not None else ()))]
        if advice:
            row["settings_warnings"] = [w.as_wire() for w in advice]
    return row


def _owned_files(cplug_id: str) -> Tuple[str, ...]:
    d = runtime.find(cplug_id)
    if d is None:
        return ()
    return purge_kept.deletable_owned_files(d.manifest.owns.files, d.manifest.data or ())


def _kept_stores(host: runtime.Host, cplug_id: str) -> List[Dict[str, Any]]:
    d = runtime.find(cplug_id)
    if d is None or not d.manifest.data:
        return []
    saved = owner_state.get(host.state_dir, d.manifest).settings
    return purge_kept.kept_stores(host.state_dir, d.manifest.data, saved)


def _removed_roots(host: runtime.Host, cplug_id: str) -> List[Path]:
    d = runtime.find(cplug_id)
    if d is None or not d.manifest.data:
        return []
    saved = owner_state.get(host.state_dir, d.manifest).settings
    return purge_removed.resolve_roots(host.state_dir, cplug_id, d.manifest.data, saved)


def _price(host: runtime.Host, cplug_id: str) -> Dict[str, Any]:
    carried = purge_guard.plan(host.folder(cplug_id), cplug_id)
    files = carried.delete + purge_owned.plan(host.state_dir, _owned_files(cplug_id)).delete
    files += purge_owned.plan_paths(_removed_roots(host, cplug_id)).delete
    size = sum(f.lstat().st_size for f in files)
    token = hashlib.sha256(f"{cplug_id}:{len(files)}:{size}".encode()).hexdigest()[:16]
    return {"id": cplug_id, "files": len(files), "bytes": size, "kept": len(carried.kept),
            "kept_stores": _kept_stores(host, cplug_id), "confirm_token": token}


def _sidecar(cplug_id: str, request: Request) -> Tuple[runtime.Host, SidecarDefinition, Any]:
    host = runtime.host_for(request.app)
    d = _shipped(cplug_id)
    if not isinstance(d, SidecarDefinition):
        raise _error(409, "not_a_sidecar", f"{cplug_id} runs inside the app and has no process to control")
    live = host.sidecar_runtime()
    if live is None:
        raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
    return host, d, live


@host_router.post("/{cplug_id}/restart")
async def restart_cplug(cplug_id: str, request: Request) -> Dict[str, Any]:
    """Stop an installed catalog cplug's process and start it again from the code and grants as they are now. Output: its row."""
    host, d, _live = _sidecar(cplug_id, request)
    if not await run_in_threadpool(host.enabled, cplug_id):
        raise _error(409, "cplug_disabled", f"turn {cplug_id} on before restarting it")
    after = await host.restart_sidecar(d)
    logger.info("cplug_restarted", cplug=cplug_id, state=after)
    host.publish(runtime.CPLUGS_TOPIC)
    return await run_in_threadpool(cplug_row, host, d)


@host_router.post("/{cplug_id}/kill")
async def kill_cplug(cplug_id: str, request: Request) -> Dict[str, Any]:
    """SIGKILL an installed catalog cplug's process group now. It stays on, with its data and grants, until restarted. Output: its row."""
    host, d, live = _sidecar(cplug_id, request)
    await live.supervisor.kill(cplug_id)
    logger.info("cplug_killed", cplug=cplug_id)
    host.publish(runtime.CPLUGS_TOPIC)
    return await run_in_threadpool(cplug_row, host, d)


@host_router.post("/{cplug_id}/purge")
async def purge_cplug(cplug_id: str, body: PurgeBody, request: Request) -> Dict[str, Any]:
    """Price, then delete a plugin's data folder and state entry (only while off or removed). Output: the price."""
    host = runtime.host_for(request.app)
    if not ID_PATTERN.match(cplug_id):
        raise _error(404, "cplug_unknown", "not a plugin id")
    found = runtime.find(cplug_id)
    known = found is not None
    try:
        held = identity.lookup(host.state_dir, cplug_id) is not None
    except identity.LedgerUnreadable as exc:
        raise _error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc
    if not known and not held and not host.folder(cplug_id).is_dir() and cplug_id not in owner_state.stored_ids(host.state_dir):
        raise _error(404, "cplug_unknown", f"no plugin {cplug_id}")
    if known and host.enabled(cplug_id):
        raise _error(409, "cplug_enabled", f"turn {cplug_id} off before purging it")
    price = await run_in_threadpool(_price, host, cplug_id)
    if body.dry_run:
        return {**price, "dry_run": True}
    if body.confirm_token != price["confirm_token"]:
        raise _error(409, "purge_stale", "the folder changed since it was priced; price it again", current=price)
    try:
        await system_lifecycle.before_purge(request.app, cplug_id)
    except system_lifecycle.PurgeHookFailed as exc:
        raise _error(503, "purge_prepare_failed", str(exc)) from exc
    live = host.sidecar_runtime()
    if live is not None and (isinstance(found, SidecarDefinition) or (held and not known)):
        live.supervisor.forget(cplug_id)
        await run_in_threadpool(live.resolve_alerts, cplug_id)
    folder = host.folder(cplug_id)
    if folder.is_dir():
        await run_in_threadpool(purge_guard.purge, folder, cplug_id, folder.parent, host.install_key(cplug_id))
    await run_in_threadpool(purge_owned.purge, host.state_dir, _owned_files(cplug_id))
    await run_in_threadpool(purge_owned.purge_paths, _removed_roots(host, cplug_id))
    await run_in_threadpool(owner_state.forget, host.state_dir, cplug_id)
    failed = await run_in_threadpool(net_routes.purge_network_data, host.state_dir, cplug_id)
    if failed and held:
        raise _error(503, "cplug_purge_incomplete", f"these stores could not be deleted: {', '.join(failed)}; purge again", stores=failed)
    if held and not known:
        try:
            await run_in_threadpool(identity.release_install, host.state_dir, cplug_id)
        except (identity.LedgerUnreadable, owner_state.StateWriteFailed) as exc:
            raise _error(503, "install_release_failed", "the data was purged but the name could not be released; purge again") from exc
    logger.info("cplug_purged", cplug=cplug_id, files=price["files"], bytes=price["bytes"])
    host.publish(runtime.CPLUGS_TOPIC)
    return {**price, "dry_run": False}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "x", path)


def _hits(route: Any, method: str, path: str) -> bool:
    return route.matches({"type": "http", "path": path, "method": method})[0] == Match.FULL


def assert_no_shadow(host_routes: APIRouter, plugin_router: APIRouter) -> None:
    prefix = plugin_router.prefix
    owner = re.match(r"/cplugs/([^/]+)", prefix)
    own_id = owner.group(1) if owner else "x"
    for route in plugin_router.routes:
        methods = getattr(route, "methods", None) or ()
        probe = _concrete(getattr(route, "path", ""))
        for method in methods:
            if any(_hits(h, method, probe) for h in host_routes.routes):
                raise ValueError(f"plugin route {method} {route.path} would shadow a host route")
            for h in host_routes.routes:
                for hm in getattr(h, "methods", None) or ():
                    if hm == method and _hits(route, method, _concrete(h.path.replace("{cplug_id}", own_id))):
                        raise ValueError(f"plugin route {method} {route.path} would answer host route {h.path}")
            if prefix.endswith("/r"):
                for reserved in identity.RESERVED_ROUTES:
                    for tail in (reserved, f"{reserved}/x"):
                        if _hits(route, method, f"{prefix}/{tail}"):
                            raise ValueError(f"plugin route {route.path}: {reserved} is a host route name")


def build_router() -> APIRouter:
    router = APIRouter()
    router.include_router(host_router)
    router.include_router(owner_switch.owner_router)
    router.include_router(sideload_routes.router)
    router.include_router(sidecar_routes.router)
    router.include_router(sidecar_ui.router)
    router.include_router(sidecar_view.router)
    router.include_router(sidecar_view.public_router)
    ahead = APIRouter()
    ahead.routes.extend([*host_router.routes, *sidecar_routes.router.routes, *sidecar_ui.router.routes, *sidecar_view.router.routes, *sidecar_view.public_router.routes])
    for d in runtime.definitions():
        if d.router is not None:
            assert_no_shadow(ahead, d.router)
            router.include_router(d.router)
    return router


router = build_router()
