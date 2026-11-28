
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from starlette.routing import Match
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from src.api.catalog_views import item_revocation_status
from src.plugins.host import (activity_log, consent as consent_mod, dependencies, destination_check, dev_routes, gate, github_install_routes, identity, inspector_routes, inspector_telemetry, net_routes, owner_switch, plugin_channels, secret_store, sideload, sideload_git, sideload_git_routes, sideload_routes, purge_guard, purge_kept, registry_routes, purge_owned, purge_removed,
                             risk, runtime, state as owner_state, system_lifecycle, ui_slots)
from src.plugins.host import absent_surfaces, renamed, renamed_entry, sidecar_routes, sidecar_ui, sidecar_view, webhook_routes
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import sandbox
from src.plugins.runtime.supervisor import NEEDS_APPROVAL, safe_mode_from_env
from src.plugins.sdk import permission_registry as registry, settings_aliases
from src.plugins.sdk.definition import CplugDefinition, SettingsVerdict, as_warning
from src.plugins.sdk.manifest import ID_PATTERN
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.item_settings_schema import SettingsSchemaError, check_key, parse_schema
from src.core.resource_push import topics
from src.core.skills import kinds
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH

logger = structlog.get_logger()

_SECRET_KEY = re.compile(r"(token|secret|password|passwd|api_?key|credential)", re.IGNORECASE)


class GrantsBody(BaseModel):
    """The app permissions (and optional ``ui_slots``) to grant (the whole set; absent ones are revoked)."""

    model_config = ConfigDict(extra="forbid")
    app: List[str]
    ui_slots: Optional[List[str]] = None


class ConsentBody(BaseModel):
    """The sheet the owner read, echoed back (``consent.py``) with the permissions ticked one by one."""

    model_config = ConfigDict(extra="forbid")
    digest: str
    body_sha: str
    grants_sha: str
    ticks: List[str] = []
    ui_slots_sha: Optional[str] = None
    slot_ticks: List[str] = []


class UpdateBody(BaseModel):
    """An owner change; ``revision`` is the one the caller read."""

    model_config = ConfigDict(extra="forbid")
    revision: StrictInt
    enabled: Optional[StrictBool] = None
    grants: Optional[GrantsBody] = None
    settings: Optional[Dict[str, Any]] = None
    consent: Optional[ConsentBody] = None
    confirm_dependents: Optional[StrictBool] = None
    activate_runtime: Optional[StrictBool] = None
    secrets: Optional[Dict[StrictStr, StrictStr]] = None


class PurgeBody(BaseModel):
    """A purge: price first (``dry_run``), then confirm with the token the price answered."""

    model_config = ConfigDict(extra="forbid")
    dry_run: StrictBool = True
    confirm_token: Optional[str] = None


host_router = APIRouter(prefix="/cplugs", tags=["cplugs"], dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)])


host_router.include_router(net_routes.router)
host_router.include_router(owner_switch.safe_mode_router)


def _error(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail, **extra})


def _install_key(host: runtime.Host, cplug_id: str) -> Optional[str]:
    try:
        return host.install_key(cplug_id)
    except identity.LedgerUnreadable:
        return None


def _secrets_status_for(host: runtime.Host, d: SidecarDefinition) -> Dict[str, Dict[str, bool]]:
    declared = tuple(s.name for s in d.manifest.network.secrets)
    if not declared:
        return {}
    key = _install_key(host, d.id)
    if not key:
        return {name: {"present": False, "needs_reentry": False} for name in declared}
    store = secret_store.SecretStore(host.state_dir)
    out: Dict[str, Dict[str, bool]] = {}
    for name in declared:
        st = store.status(key, d.manifest, name)
        out[name] = {"present": bool(st.get("secret_present")), "needs_reentry": bool(st.get("needs_reentry"))}
    return out


def _agent_plugin_rows(host: runtime.Host) -> List[Dict[str, Any]]:
    path = db_path_for(host.state_dir)
    if not path.exists():
        return []
    conn = connect(path, create=False)
    try:
        rows = [r for r in InstallLedger(conn).list() if r.kind == kinds.KIND_PLUGIN]
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        gh = identity.is_unverified_github(row.item_id)
        local = sideload.is_local(row.item_id)
        trust_tier = "unverified_github" if gh else ("local_dev" if local else "warez_verified")
        trust_badge = "Unverified GitHub Repo" if gh else ("Local Dev" if local else "Warez Verified")
        gh_parts = sideload_git.github_owner_repo(row.source_index_url)
        git_source = (
            {"owner": gh_parts[0], "repo": gh_parts[1], "url": row.source_index_url}
            if gh_parts is not None
            else None
        )
        out.append({
            "id": row.item_id.partition("/")[2] or row.name,
            "item_id": row.item_id,
            "install_id": row.install_id,
            "publisher": row.item_id.partition("/")[0],
            "name": row.name,
            "version": row.version,
            "kind": "agent-plugin",
            "trust_tier": trust_tier,
            "trust_badge": trust_badge,
            "unverified": gh or local,
            "scope": row.scope,
            "project_path": None if row.project_path == GLOBAL_PROJECT_PATH else row.project_path,
            "enabled": True,
            "state": "active",
            "runtime": "agent-plugin",
            "runtime_paused": False,
            "secrets_status": {},
            "git_source": git_source,
            "source_index_url": row.source_index_url,
        })
    return out


def _third_party_runtime_active(host: runtime.Host) -> bool:
    live = host.sidecar_runtime()
    if live is not None and hasattr(live, "safe_mode"):
        return not any(live.safe_mode().values())
    return owner_switch.read(host.state_dir) and not safe_mode_from_env()


def cplug_row(host: runtime.Host, d: CplugDefinition) -> Dict[str, Any]:
    m = d.manifest
    st = owner_state.get(host.state_dir, m)
    needs = [p for p in m.permissions if p not in st.grants]
    consent_required = risk.needs_consent(m.tier)
    owed = risk.consent_owed(m.tier, m.code_digest, st.digest)
    if owed and st.grants:
        needs = list(m.permissions)
    blocked = list(gate.blocked_by(m.id, host.state_dir))
    sidecar = isinstance(d, SidecarDefinition)
    live = host.sidecar_runtime() if sidecar else None
    process = live.supervisor.state(d.id) if live is not None else None
    runtime_paused = bool(
        sidecar and live is not None and getattr(live, "supervisor", None) is not None
        and hasattr(live.supervisor, "is_paused") and live.supervisor.is_paused(d.id)
    )
    meta = identity.trust_metadata(d)
    revoked = bool(
        process == "revoked"
        or (
            sidecar
            and live is not None
            and getattr(live, "supervisor", None) is not None
            and d.id in getattr(live.supervisor, "_revoked", ())
        )
    )
    revocation_reason: Optional[str] = "revoked_in_index" if revoked else None
    revoked_since: Optional[str] = None
    if sidecar and live is not None and callable(getattr(live, "_catalog_cache", None)):
        cache = live._catalog_cache()
        if cache is not None and (hasattr(cache, "snapshot") or hasattr(cache, "revocations")):
            rec = identity.lookup(host.state_dir, d.id)
            kid = rec.publisher_key_id if rec is not None else ""
            snap = cache.snapshot() if hasattr(cache, "snapshot") else None
            cat_rev, cat_reason, cat_since = item_revocation_status(
                item_id=getattr(d, "item_id", d.id),
                version=m.version,
                publisher_key_id=kid,
                snapshot=snap,
                cache=cache,
            )
            if cat_rev:
                revoked = True
                revocation_reason = cat_reason or revocation_reason or "revoked"
                revoked_since = cat_since
    detail = host.unavailable.get(d.id)
    if not st.enabled:
        status = "disabled"
    elif d.id in host.unavailable:
        status = "unavailable"
    elif revoked:
        status, detail = "unavailable", (revocation_reason or "revoked")
    elif runtime_paused or process == "paused":
        status, detail = "paused", "paused"
    elif sidecar and live is not None and process not in ("running", "idle", "declarative") and not ((needs or owed) and process in ("disabled", NEEDS_APPROVAL)):
        status, detail = "unavailable", process
    elif needs or owed:
        status = "needs_approval"
    elif blocked:
        status = "inert"
    else:
        status = "active"
    raw_ui_meta = getattr(m, "ui_meta", None)
    raw_widget = raw_ui_meta.get("widget") if isinstance(raw_ui_meta, Mapping) else None
    slot_meta = ui_slots.row_metadata(m, plugin_id=m.id)
    return {
        "id": m.id, "name_key": m.name_key, "description_key": m.description_key, "version": m.version,
        "icon": m.icon, "tier": m.tier, "author": m.author, "surfaces": m.surfaces.as_wire(),
        "permissions": {"app": list(m.permissions)},
        "grants": {"app": list(st.grants), "ui_slots": list(getattr(st, "ui_slot_grants", ()))},
        "granted_ui_slots": list(owner_state.granted_ui_slots(host.state_dir, m)),
        "enabled": st.enabled,
        "risks": {p: registry.risk_of(p, m.tier) for p in m.permissions}, "consent_required": consent_required,
        "reasons": {p: r for p in m.permissions if (r := consent_mod.reason_for(m, p))},
        "warnings": consent_mod.warnings_of(m),
        "state": status, "needs": needs, "detail": detail,
        "runtime": "sidecar" if sidecar else "compiled", "trust": m.tier, "process": process,
        "kind": meta["kind"], "trust_tier": meta["trust_tier"], "trust_badge": meta["trust_badge"],
        "scope": "global", "project_path": None,
        "runtime_paused": runtime_paused,
        "runtime_active": _third_party_runtime_active(host),
        "secrets_status": _secrets_status_for(host, d) if sidecar else {},
        "git_source": sideload_git.records(host.state_dir).get(d.id) if sidecar else None,
        "watchdog": inspector_telemetry.watchdog_row_summary(host.state_dir, live.supervisor, d.id, d.folder) if sidecar and live is not None else None,
        "dev_lease": inspector_telemetry.lease_summary(host.state_dir, d.id) if sidecar else None,
        "unverified": meta["unverified"],
        "revoked": revoked,
        "revocation_reason": revocation_reason,
        "revoked_since": revoked_since,
        "changed_files": sideload.items(host.state_dir).get(d.id, {}).get("changed", []) if sidecar and sideload.is_local(d.item_id) else [],
        "name": m.name if sidecar else None, "description": m.description if sidecar else None,
        "publisher": d.item_id.partition("/")[0] if sidecar else None,
        "tools": ([t["name"] for t in m.tools] if process in ("running", "idle") else []) if sidecar else None,
        "routes": list(m.routes) if sidecar else None,
        "declared_tools": [t["name"] for t in m.tools if isinstance(t, dict)] if sidecar else None,
        "install_key": _install_key(host, d.id) if sidecar else None,
        "unrendered_surfaces": absent_surfaces.listed(d.id, m.version) if sidecar else None,
        "views": [
            {"name": v["name"], "surfaces": list(v.get("surfaces", ())), "fits": v.get("fits"), **({"popout": v["popout"]} if "popout" in v else {})}
            for v in m.views
        ] if (sidecar or m.views) else None,
        "declarative_widget": dict(raw_widget) if isinstance(raw_widget, Mapping) else None,
        "page": dict(m.page) if sidecar and m.page else None, "page_problem": m.page_problem if sidecar else None,
        "topics": list(m.topics) if sidecar else None,
        "preview": f"/cplugs/{d.id}/preview?rev={m.code_digest[:12]}" if sidecar and m.preview else None,
        "icon_url": f"/cplugs/{d.id}/icon?rev={m.code_digest[:12]}" if sidecar and getattr(m, "icon_file", "") else None,
        "screenshots": [
            {"url": f"/cplugs/{d.id}/screenshots/{idx}?rev={m.code_digest[:12]}", "source": "author"}
            for idx, _p in enumerate(
                (tuple(getattr(m, "screenshots", ()) or ()) or ((m.preview,) if m.preview else ())),
                start=1,
            )
        ] if sidecar and (getattr(m, "screenshots", ()) or m.preview) else [],
        "settings": settings_aliases.merged(runtime.settings_defaults(m.settings_schema), st.settings, m.settings_aliases),
        "settings_schema": dict(m.settings_schema),
        "storage_bytes": host.storage(d.id).size_bytes(), "revision": st.revision,
        "requires": list(m.requires), "requires_off": [r for r in m.requires if not host.enabled(r)],
        "blocked_by": blocked,
        "requires_core": list(m.requires_core), "min_app_version": m.min_app_version,
        "dependencies": dependencies.dependency_view(m, host.state_dir),
        **slot_meta,
    }


def _orphans(host: runtime.Host) -> List[Dict[str, Any]]:
    root = host.state_dir / owner_state.STATE_DIR_NAME
    shipped = {d.id for d in runtime.definitions()} | {d.id for d in runtime.listed()} | runtime.renamed_ids()
    if not root.is_dir():
        return []
    rows = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and ID_PATTERN.match(p.name) and p.name not in shipped and p.name not in identity.HOST_WORDS):
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
    cplug_id = runtime.canonical_id(cplug_id)
    target = None if runtime.find(cplug_id) is not None else runtime.legacy_target(cplug_id)
    if target is None:
        return cplug_id, body
    if body is None:
        return target.id, None
    carried = dict(body.settings or {})
    if body.enabled is not None:
        carried[target.manifest.legacy_ids[cplug_id]] = body.enabled
    return target.id, body.model_copy(update={"enabled": None, "grants": None, "settings": carried or None})


def _attach_catalog_screenshots(request: Request, rows: List[Dict[str, Any]]) -> None:
    services = getattr(request.app.state, "services", None)
    cache = getattr(getattr(services, "catalog", None), "index_cache", None)
    snap = getattr(cache, "_snapshot", None) if cache is not None else None
    verified = getattr(snap, "verified", None) if snap is not None else None
    if verified is None:
        return
    by_item: Dict[str, List[Dict[str, Any]]] = {}
    for item in (*verified.items, *verified.untrusted_items):
        shots = getattr(item.card, "screenshots", None) or ()
        if not shots:
            continue
        by_item[item.id] = [
            {
                "sha": s.sha256,
                "w": s.w,
                "h": s.h,
                "source": s.source,
                **({"surface": s.surface} if s.surface else {}),
                **({"caption": s.caption} if s.caption else {}),
            }
            for s in shots
        ]
    for row in rows:
        if row.get("screenshots"):
            continue
        pub, cid = row.get("publisher"), row.get("id")
        if isinstance(pub, str) and isinstance(cid, str):
            found = by_item.get(f"{pub}/{cid}")
            if found:
                row["screenshots"] = found


@host_router.get("")
async def list_cplugs(request: Request, include_agent_plugins: bool = Query(False)) -> Dict[str, Any]:
    """Every plugin, shipped then removed (and installed agent-plugins when ``include_agent_plugins=true``). Output: {cplugs}."""
    host = runtime.host_for(request.app)

    def _collect() -> List[Dict[str, Any]]:
        rows = [cplug_row(host, d) for d in runtime.listed()] + _orphans(host)
        if include_agent_plugins:
            rows.extend(_agent_plugin_rows(host))
        _attach_catalog_screenshots(request, rows)
        return rows

    return {"cplugs": await run_in_threadpool(_collect)}


@host_router.get("/slots")
async def list_slots(request: Request) -> Dict[str, Any]:
    """Active, consented, validated UI slot contributions and owners across enabled plugins."""
    host = runtime.host_for(request.app)
    live = host.sidecar_runtime()
    safe_active = any(live.safe_mode().values()) if live is not None and hasattr(live, "safe_mode") else False
    sup = getattr(live, "supervisor", None) if live is not None else None
    return await run_in_threadpool(
        lambda: ui_slots.registry_for(host.state_dir).resolve(
            host=host,
            definitions=runtime.listed(),
            safe_mode_active=safe_active,
            supervisor=sup,
        )
    )


@host_router.get("/{cplug_id}")
async def get_cplug(cplug_id: str, request: Request) -> Dict[str, Any]:
    """One shipped plugin (a retired id answers with the plugin that absorbed it). Output: its row."""
    host = runtime.host_for(request.app)
    return await run_in_threadpool(cplug_row, host, _shipped(_folded(cplug_id)[0]))


@host_router.get("/{cplug_id}/sheet")
async def get_sheet(cplug_id: str, request: Request) -> Dict[str, Any]:
    """The permission sheet to read before enabling or granting (consent.py). Output: the sheet."""
    host = runtime.host_for(request.app)
    d = _shipped(runtime.canonical_id(cplug_id))

    def _build_sheet() -> Dict[str, Any]:
        st = owner_state.get(host.state_dir, d.manifest)
        return consent_mod.sheet(d.manifest, st.grants, st.ui_slot_grants)

    shown = await run_in_threadpool(_build_sheet)
    meta = identity.trust_metadata(d)
    shown = {**shown, "kind": meta["kind"], "trust_tier": meta["trust_tier"], "trust_badge": meta["trust_badge"]}
    if isinstance(d, SidecarDefinition) and meta["unverified"]:
        changed = sideload.items(host.state_dir).get(d.id, {}).get("changed", []) if sideload.is_local(d.item_id) else []
        shown = {**shown, "unverified": True, "changed_files": changed}
    return shown


@host_router.get("/{cplug_id}/activity")
async def get_activity(cplug_id: str, request: Request, limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """The newest capability calls this plugin made (never a query, a line of text or a secret). Output: {activity}."""
    host = runtime.host_for(request.app)
    cplug_id = _shipped(runtime.canonical_id(cplug_id)).id
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
        if body.grants.ui_slots is not None:
            extra_slots = sorted(set(body.grants.ui_slots) - set(consent_mod.declared_ui_slots(m)))
            if extra_slots:
                raise _error(422, "grant_not_asked", f"{m.id} does not ask for ui slots {', '.join(extra_slots)}")
    if body.settings is not None:
        try:
            schema = parse_schema(m.settings_schema)
        except SettingsSchemaError as exc:
            raise _error(422, "settings_invalid", f"settings_schema: {exc}") from exc
        for key, value in settings_aliases.translate(body.settings, m.settings_aliases).items():
            refusal = "setting_secret" if _SECRET_KEY.search(key) else check_key(schema, key, value)
            if refusal:
                raise _error(422, "settings_invalid", f"{key}: {refusal}")
        folder_problem = destination_check.refused(m.data, settings_aliases.translate(body.settings, m.settings_aliases))
        if folder_problem:
            raise _error(422, "destination_refused", folder_problem)
    if body.secrets is not None:
        if not isinstance(d, SidecarDefinition):
            raise _error(422, "secret_unknown", f"{m.id} declares no secrets")
        declared = {s.name for s in m.network.secrets}
        for sec_name, sec_val in body.secrets.items():
            if sec_name not in declared:
                raise _error(404, "secret_unknown", f"{m.id} declares no secret {sec_name}")
            if not secret_store.SecretStore._bindings(m, sec_name):
                raise _error(422, "secret_unbound", f"no network host or webhook of {m.id} uses {sec_name}")
            if not isinstance(sec_val, str) or not secret_store.relay_keychain.is_safe_secret(sec_val):
                raise _error(422, "secret_invalid", "a value may only use letters, digits and _ . ~ + / = : - (no spaces or quotes)")


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
    async with dev_routes.reload_lock(host.state_dir, d.manifest.id):
        d = _shipped(cplug_id)
        _check(d, body)
        verdict = await run_in_threadpool(_own_check, d, body)

        def mutate(st: owner_state.CplugState) -> owner_state.CplugState:
            changes: Dict[str, Any] = {}
            if body.enabled is not None:
                changes["enabled"] = body.enabled
            if body.grants is not None:
                changes["grants"] = tuple(p for p in d.manifest.permissions if p in body.grants.app)
                if body.grants.ui_slots is not None:
                    declared_slots = consent_mod.declared_ui_slots(d.manifest)
                    changes["ui_slot_grants"] = tuple(s for s in declared_slots if s in body.grants.ui_slots)
            wanted = changes.get("grants", st.grants)
            wanted_slots = changes.get("ui_slot_grants", st.ui_slot_grants)
            declared_slots = consent_mod.declared_ui_slots(d.manifest)
            slot_widening = not set(wanted_slots) <= set(st.ui_slot_grants)
            moved = body.consent is not None and st.digest != d.manifest.code_digest
            need_slot_check = bool(
                (body.grants is not None and body.grants.ui_slots is not None)
                or (body.consent is not None and body.consent.ui_slots_sha is not None)
                or (declared_slots and (body.enabled is True or slot_widening or moved))
            )
            if risk.needs_consent(d.manifest.tier) and (
                body.enabled is True or not set(wanted) <= set(st.grants) or slot_widening or moved
            ):
                consent_mod.check(
                    d.manifest,
                    wanted,
                    st.grants,
                    body.consent.model_dump() if body.consent else None,
                    requested_slots=wanted_slots if need_slot_check else None,
                    current_slots=st.ui_slot_grants,
                )
                changes["digest"] = d.manifest.code_digest
            if body.settings is not None:
                changes["settings"] = {**st.settings, **settings_aliases.translate(body.settings, d.manifest.settings_aliases)}
            return replace(st, **changes)

        before = await run_in_threadpool(host.enabled, cplug_id)
        held = await run_in_threadpool(owner_state.get, host.state_dir, d.manifest)
        if body.enabled is True and isinstance(d, SidecarDefinition):
            live = host.sidecar_runtime()
            if live is not None:
                sup_rev = live.supervisor.state(d.id) == "revoked" or d.id in getattr(live.supervisor, "_revoked", ())
                if sup_rev:
                    raise _error(409, "version_revoked", f"{cplug_id} has been revoked and cannot be enabled")
                cache = live._catalog_cache() if callable(getattr(live, "_catalog_cache", None)) else None
                if cache is not None and (hasattr(cache, "snapshot") or hasattr(cache, "revocations")):
                    rec = await run_in_threadpool(identity.lookup, host.state_dir, d.id)
                    kid = rec.publisher_key_id if rec is not None else ""
                    snap = cache.snapshot() if hasattr(cache, "snapshot") else None
                    cat_rev, cat_reason, _since = item_revocation_status(
                        item_id=getattr(d, "item_id", d.id),
                        version=d.manifest.version,
                        publisher_key_id=kid,
                        snapshot=snap,
                        cache=cache,
                    )
                    if cat_rev:
                        code = "key_untrusted" if cat_reason == "key_revoked" else "version_revoked"
                        raise _error(409, code, f"{cplug_id} has been revoked ({code}) and cannot be enabled")
        if body.enabled is True and not before:
            blockers = await run_in_threadpool(dependencies.enable_blockers, d.manifest)
            if blockers:
                why = dependencies.format_blockers(blockers)
                raise _error(409, "requirements_unmet", f"{cplug_id} cannot be turned on: {why}", unmet=blockers)
        if body.enabled is False and before and not body.confirm_dependents:
            dependents = await run_in_threadpool(dependencies.enabled_dependents, cplug_id, host.state_dir)
            if dependents:
                raise _error(409, "has_dependents", f"{', '.join(dependents)} need {cplug_id}; send confirm_dependents to turn it off anyway",
                             dependents=dependents)
        if body.activate_runtime is True:
            live = host.sidecar_runtime()
            if live is None:
                raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
            if live._env_safe():
                raise _error(409, "safe_mode_forced", "runtime safe mode is forced by environment and cannot be activated")
        store: Optional[secret_store.SecretStore] = None
        secrets_snapshot: Optional[secret_store.SecretsSnapshot] = None
        if body.secrets:
            if body.revision != held.revision:
                raise _error(409, "stale_revision", f"revision is {held.revision}", current=held.as_wire())
            try:
                mutate(held)
            except consent_mod.ConsentRefused as exc:
                raise _error(exc.status, exc.code, exc.detail) from exc
            store = secret_store.SecretStore(host.state_dir)
            try:
                install_key = await run_in_threadpool(host.install_key, cplug_id)
                secrets_snapshot = await run_in_threadpool(store.set_many, install_key, d.manifest, body.secrets)
            except identity.LedgerUnreadable as exc:
                raise _error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc
            except secret_store.SecretError as exc:
                status_code = 404 if exc.code == "secret_unknown" else (503 if exc.code in ("keychain_refused", "secrets_unreadable", "secrets_unwritable") else 422)
                raise _error(status_code, exc.code, str(exc)) from exc
        try:
            after = await run_in_threadpool(owner_state.update, host.state_dir, d.manifest, body.revision, mutate)
        except owner_state.StaleRevision as exc:
            if store is not None and secrets_snapshot is not None:
                await run_in_threadpool(store.restore_snapshot, secrets_snapshot)
            raise _error(409, "stale_revision", str(exc), current=exc.current.as_wire()) from exc
        except consent_mod.ConsentRefused as exc:
            if store is not None and secrets_snapshot is not None:
                await run_in_threadpool(store.restore_snapshot, secrets_snapshot)
            raise _error(exc.status, exc.code, exc.detail) from exc
        except owner_state.StateWriteFailed as exc:
            if store is not None and secrets_snapshot is not None:
                await run_in_threadpool(store.restore_snapshot, secrets_snapshot)
            raise _error(503, "cplug_state_unwritable", "the plugin state file could not be written") from exc
        if body.activate_runtime is not None:
            live = host.sidecar_runtime()
            if live is not None:
                await run_in_threadpool(owner_switch.write, host.state_dir, bool(body.activate_runtime))
                ok = await live.set_switch(bool(body.activate_runtime))
                if body.activate_runtime and not ok:
                    raise _error(409, "safe_mode_forced", "runtime safe mode is forced by environment and cannot be activated")
        if after.enabled != before:
            if not after.enabled:
                from src.plugins.host import dev_lease  # noqa: PLC0415

                dev_lease.store_for(host.state_dir).revoke_plugin(cplug_id)
            await host.switched(cplug_id, after.enabled)
        else:
            if after.enabled and isinstance(d, SidecarDefinition) and (tuple(after.grants) != tuple(held.grants) or after.digest != held.digest):
                await host.restart_sidecar(d)
            live_rt = host.sidecar_runtime()
            safe_active = any(live_rt.safe_mode().values()) if live_rt is not None and hasattr(live_rt, "safe_mode") else False
            sup = getattr(live_rt, "supervisor", None) if live_rt is not None else None
            defs = live_rt._all_definitions() if live_rt is not None and hasattr(live_rt, "_all_definitions") else runtime.listed()
            tier0_reg = getattr(live_rt, "tier0_channels", None) if live_rt is not None else None
            await run_in_threadpool(
                lambda: (
                    plugin_channels.sync_plugin(
                        host,
                        d,
                        safe_mode_active=safe_active,
                        supervisor=sup,
                        tier0_registry=tier0_reg,
                    ),
                    ui_slots.registry_for(host.state_dir).sync(
                        defs,
                        host=host,
                        safe_mode_active=safe_active,
                        supervisor=sup,
                    ),
                )
            )
        stored_advice: Sequence[Any] = ()
        if body.settings is not None and verdict is not None and verdict.after_store is not None:
            stored_advice = await run_in_threadpool(verdict.after_store)
        if body.settings is not None:
            await host.settings_saved(cplug_id)
        logger.info("cplug_state_changed", cplug=cplug_id, enabled=after.enabled, grants=list(after.grants),
                    ui_slot_grants=list(after.ui_slot_grants), revision=after.revision)
        if after.ui_slot_grants != held.ui_slot_grants or after.enabled != before or after.digest != held.digest:
            host.publish(topics.CPLUG_SLOTS)
        host.publish(runtime.CPLUGS_TOPIC)
        inspector_telemetry.telemetry_for(host.state_dir).notify(cplug_id)
        row = await run_in_threadpool(cplug_row, host, d)
        if body.settings is not None:
            advice = await run_in_threadpool(destination_check.warnings, d.manifest.data,
                                             settings_aliases.translate(body.settings, d.manifest.settings_aliases), host.state_dir)
            advice = [*advice, *(as_warning(w) for w in (verdict.warnings if verdict is not None else ())), *(as_warning(w) for w in stored_advice)]
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


def _renamed_from(cplug_id: str) -> str:
    d = runtime.find(cplug_id)
    return d.manifest.renamed_from if isinstance(d, CplugDefinition) else ""


def _price(host: runtime.Host, cplug_id: str) -> Dict[str, Any]:
    carried = purge_guard.plan_with_previous(host.folder(cplug_id), cplug_id, _renamed_from(cplug_id))
    files = carried.delete + purge_owned.plan(host.state_dir, _owned_files(cplug_id)).delete
    files += purge_owned.plan_paths(_removed_roots(host, cplug_id)).delete
    size = sum(f.lstat().st_size for f in files)
    token = hashlib.sha256(f"{cplug_id}:{len(files)}:{size}".encode()).hexdigest()[:16]
    return {"id": cplug_id, "files": len(files), "bytes": size, "kept": len(carried.kept),
            "kept_stores": _kept_stores(host, cplug_id), "confirm_token": token}


def _sidecar(cplug_id: str, request: Request) -> Tuple[runtime.Host, SidecarDefinition, Any]:
    host = runtime.host_for(request.app)
    d = _shipped(runtime.canonical_id(cplug_id))
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
    async with dev_routes.reload_lock(host.state_dir, d.id):
        host, d, _live = _sidecar(cplug_id, request)
        if not await run_in_threadpool(host.enabled, d.id):
            raise _error(409, "cplug_disabled", f"turn {d.id} on before restarting it")
        st = await run_in_threadpool(owner_state.get, host.state_dir, d.manifest)
        if risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest):
            raise _error(409, "needs_approval", f"{d.id} changed since it was approved; approve it before restarting it")
        after = await host.restart_sidecar(d)
        logger.info("cplug_restarted", cplug=d.id, state=after)
        host.publish(runtime.CPLUGS_TOPIC)
        inspector_telemetry.telemetry_for(host.state_dir).notify(d.id)
        return await run_in_threadpool(cplug_row, host, d)


@host_router.post("/{cplug_id}/kill")
async def kill_cplug(cplug_id: str, request: Request) -> Dict[str, Any]:
    """SIGKILL an installed catalog cplug's process group now. It stays on, with its data and grants, until restarted. Output: its row."""
    host, d, live = _sidecar(cplug_id, request)
    async with dev_routes.reload_lock(host.state_dir, d.id):
        host, d, live = _sidecar(cplug_id, request)
        await live.supervisor.kill(d.id)
        logger.info("cplug_killed", cplug=d.id)
        host.publish(runtime.CPLUGS_TOPIC)
        inspector_telemetry.telemetry_for(host.state_dir).notify(d.id)
        return await run_in_threadpool(cplug_row, host, d)


@host_router.post("/{cplug_id}/purge")
async def purge_cplug(cplug_id: str, body: PurgeBody, request: Request) -> Dict[str, Any]:
    """Price, then delete a plugin's data folder and state entry (only while off or removed). Output: the price.

    A renamed plugin's OLD id is refused ``409 cplug_renamed`` naming the current id, on or off: its folder and state entry are the
    rename's rollback copy (and the live one when a later slice's copy check fails) until slice S11 says how old data retires (#3260 r2 M1).
    """
    host = runtime.host_for(request.app)
    if not ID_PATTERN.match(cplug_id):
        raise _error(404, "cplug_unknown", "not a plugin id")
    if cplug_id in runtime.renamed_ids():
        new_id = runtime.canonical_id(cplug_id)
        raise _error(409, "cplug_renamed", f"{cplug_id} was renamed to {new_id}; its old data is kept", renamed_to=new_id)
    async with dev_routes.reload_lock(host.state_dir, cplug_id):
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
            if hasattr(live.supervisor, "forget_plugin"):
                await live.supervisor.forget_plugin(cplug_id)
            else:
                live.supervisor.forget(cplug_id)
            await run_in_threadpool(live.resolve_alerts, cplug_id)
        folder = host.folder(cplug_id)
        if folder.is_dir():
            await run_in_threadpool(purge_guard.purge, folder, cplug_id, folder.parent, host.install_key(cplug_id))
        await run_in_threadpool(purge_guard.purge_previous, folder, _renamed_from(cplug_id))
        await run_in_threadpool(sandbox.remove_profile, folder)
        await run_in_threadpool(purge_owned.purge, host.state_dir, _owned_files(cplug_id))
        await run_in_threadpool(purge_owned.purge_paths, _removed_roots(host, cplug_id))
        await run_in_threadpool(owner_state.forget, host.state_dir, cplug_id)
        await run_in_threadpool(renamed_entry.forget_old_entries, host.state_dir, cplug_id)
        failed = await run_in_threadpool(net_routes.purge_network_data, host.state_dir, cplug_id)
        if failed and held:
            raise _error(503, "cplug_purge_incomplete", f"these stores could not be deleted: {', '.join(failed)}; purge again", stores=failed)
        if held and not known:
            try:
                await run_in_threadpool(identity.release_install, host.state_dir, cplug_id)
            except (identity.LedgerUnreadable, owner_state.StateWriteFailed) as exc:
                raise _error(503, "install_release_failed", "the data was purged but the name could not be released; purge again") from exc
        logger.info("cplug_purged", cplug=cplug_id, files=price["files"], bytes=price["bytes"])
        await run_in_threadpool(
            lambda: plugin_channels.unregister_plugin(
                cplug_id,
                host=host,
                tier0_registry=getattr(live, "tier0_channels", None),
            )
        )
        host.publish(runtime.CPLUGS_TOPIC)
        host.publish(topics.CPLUG_SLOTS)
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
    router.include_router(inspector_routes.router)
    router.include_router(owner_switch.owner_router)
    router.include_router(dev_routes.router)
    router.include_router(sideload_routes.router)
    router.include_router(registry_routes.router)
    router.include_router(sideload_git_routes.router)
    router.include_router(github_install_routes.router)
    router.include_router(sidecar_routes.router)
    router.include_router(sidecar_ui.router)
    router.include_router(sidecar_view.router)
    router.include_router(sidecar_view.public_router)
    router.include_router(webhook_routes.public_router)
    ahead = APIRouter()
    ahead.routes.extend([*host_router.routes, *inspector_routes.router.routes, *sidecar_routes.router.routes, *sidecar_ui.router.routes, *sidecar_view.router.routes, *sidecar_view.public_router.routes, *webhook_routes.public_router.routes])
    for d in runtime.definitions():
        if d.router is not None:
            assert_no_shadow(ahead, d.router)
            router.include_router(d.router)
    for d in runtime.definitions():
        moved = renamed.alias_router(d)
        if moved is not None:
            assert_no_shadow(ahead, moved)
            router.include_router(moved)
    return router


router = build_router()
