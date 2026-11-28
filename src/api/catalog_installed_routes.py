
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.api.catalog_install_support import (
    fetch_and_stage,
    refuse_409,
    resolve_item,
)
from src.api.catalog_consent import (
    carries_scripts,
    consent_409,
    consent_carried,
)
from src.api.catalog_contents_routes import update_diff
from src.api.catalog_loadout_rules import removable_members
from src.api.catalog_installed_support import (
    apply_update_now,
    patch_now,
    refuse_builtin,
    row_now,
    stale_409,
    uninstall_now,
)
from src.api import catalog_cplug_gates, catalog_mod_gates
from src.api.catalog_routes import refuse_empty
from src.api.catalog_installed_watch import annotate_watch
from src.api.catalog_views import installed_view, item_revocation_status
from src.core.catalog import install_reporter
from src.core.catalog.permission_diff import compute_permission_diff
from src.core.catalog.verify import check_digest
from src.core.catalog.verify_types import KEY_UNTRUSTED, VERSION_REVOKED
from src.core.plugin_registry import plugin_layout
from src.core.skills.code_gate import staged_plugin_declares_code
from src.core.skills.digest import hash_file
from src.core.skills.install_types import ALREADY_INSTALLED, DIGEST_MISMATCH
from src.core.skills.installer import discard_staging
from src.core.skills.targets import TrashFolderIsLink
from src.core.skills.kinds import KIND_CPLUG, KIND_MOD, resolve_manifest_path
from src.core.skills.updates import update_available
from src.models.catalog_api import (
    InstalledItemView,
    InstalledPatchRequest,
    InstalledUpdateRequest,
    UninstallResponse,
)

router = APIRouter(tags=["catalog"])


def _cplug_reload_lock(request: Request, row: Any) -> Any:
    if getattr(row, "kind", "") != KIND_CPLUG:
        return contextlib.nullcontext()
    services = getattr(request.app.state, "services", None)
    sr = getattr(services, "settings_reader", None)
    live = getattr(request.app.state, "sidecar_runtime", None)
    state_dir = sr.state_dir() if (sr is not None and hasattr(sr, "state_dir")) else getattr(live, "state_dir", None)
    item_id = str(getattr(row, "item_id", "") or "")
    name = item_id.partition("/")[2] or str(getattr(row, "name", "") or "")
    if state_dir is None or not name:
        return contextlib.nullcontext()
    from src.plugins.host import dev_routes  # noqa: PLC0415

    return dev_routes.reload_lock(Path(state_dir), name)


@router.delete(
    "/catalog/installed/{install_id}",
    response_model=UninstallResponse,
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)
async def uninstall_item(
    request: Request, install_id: str
) -> UninstallResponse:
    """Move one install's copies to the trash and forget the row.

    Answers where each copy went, which ones were already gone, and - for
    a loadout - which of its members nothing else still needs.

    **REMOVING A LOADOUT NEVER REMOVES A MEMBER.** A member can belong to
    another loadout, or have been installed on its own long before any
    bundle mentioned it, and both are ordinary. So the members that
    nothing else claims are OFFERED back in ``removable_members`` and the
    decision stays with the person. Removing one is a separate, explicit
    uninstall of that item.

    THE OFFER IS COMPUTED BEFORE THE ROW GOES, because the membership
    rows hang off it with ``ON DELETE CASCADE`` and there would be
    nothing left to ask afterwards.

    Raises:
        HTTPException(404): no ledger row carries that id.
        HTTPException(409): a trash folder is a symlink (``target_unsafe``).
        HTTPException(500): a rename failed. The row is still there and
            still names every copy.
    """
    row = await asyncio.to_thread(row_now, request, install_id)
    offered = await asyncio.to_thread(removable_members, request, row)
    if row.kind == KIND_CPLUG:
        refuse_builtin(row)
    async with _cplug_reload_lock(request, row):
        if row.kind == KIND_CPLUG:
            await catalog_cplug_gates.stop_before_uninstall(request, row)
        try:
            response = await asyncio.to_thread(uninstall_now, request, install_id)
        except TrashFolderIsLink:
            raise HTTPException(status_code=409, detail={"code": "target_unsafe", "detail": "a trash folder is a link; nothing was moved"})
        if row.kind == KIND_CPLUG:
            await asyncio.to_thread(catalog_cplug_gates.release_if_empty, request, row)
            await asyncio.to_thread(catalog_cplug_gates.reload_and_push, request)
    response.removable_members = offered
    return response


@router.patch(
    "/catalog/installed/{install_id}",
    response_model=InstalledItemView,
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)
async def patch_installed(
    request: Request, install_id: str, body: InstalledPatchRequest
) -> InstalledItemView:
    """Set whether this install may be updated silently.

    The badge on the answer is computed against the HELD index, exactly
    as the listing's is, so this never triggers a fetch.

    Raises:
        HTTPException(404): no ledger row carries that id.
        HTTPException(409): ``stale_revision`` carrying the current row,
            or ``auto_update_global_only`` for a project-scope row.
    """
    services = request.app.state.services
    snapshot = services.catalog.index_cache.snapshot()
    row = await asyncio.to_thread(patch_now, request, install_id, body)
    view = installed_view(row, snapshot, cache=services.catalog.index_cache)
    await asyncio.to_thread(annotate_watch, services, [row], [view])
    return view


@router.post(
    "/catalog/installed/{install_id}/update",
    response_model=InstalledItemView,
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)
async def update_installed(
    request: Request, install_id: str, body: InstalledUpdateRequest
) -> InstalledItemView:
    """Apply the catalog's newest build of something already installed.

    Raises:
        HTTPException(404): no such install, or the index no longer
            carries the item it names.
        HTTPException(409): ``stale_revision`` with the current row,
            ``already_installed`` when there is nothing newer,
            ``key_untrusted``, ``digest_mismatch``, or
            ``consent_required`` carrying the new manifest text, its
            script list and its sha.
        HTTPException(502): the index or the tarball could not be fetched.
        HTTPException(500): a copy or a rename failed; the response names
            the journal that resolves it.
    """
    services = request.app.state.services
    row = await asyncio.to_thread(row_now, request, install_id)
    refuse_builtin(row)
    if row.revision != body.expected_revision:
        raise stale_409(row)

    snapshot = await services.catalog.index_cache.get()
    refuse_empty(snapshot)
    item, version = resolve_item(snapshot, row.item_id, row.kind, cache=services.catalog.index_cache)
    if not update_available(row, version):
        raise refuse_409(
            ALREADY_INSTALLED,
            f"{row.item_id!r} is up to date at {row.version!r}",
        )
    return await apply_version(request, row, item, version, body, snapshot)


def _resolve_installed_dir(services: Any, row: Any) -> Optional[Path]:
    catalog = getattr(services, "catalog", None)
    install_id = getattr(row, "install_id", "")
    if catalog is not None and hasattr(catalog, "ledger") and install_id:
        try:
            with catalog.ledger() as ledger:
                for target in ledger.targets(install_id):
                    candidate = Path(target.path)
                    if candidate.is_dir():
                        return candidate
        except Exception:
            pass
    settings_reader = getattr(services, "settings_reader", None)
    if settings_reader is not None and getattr(row, "kind", "") == KIND_CPLUG:
        try:
            state_dir = settings_reader.state_dir()
            name = str(getattr(row, "item_id", "")).partition("/")[2] or getattr(row, "name", "")
            if name:
                croot = plugin_layout.code_root(state_dir, name)
                if croot is not None and croot.is_dir():
                    return croot
        except Exception:
            pass
    return None


def _check_revoked_for_update(services: Any, snapshot: Any, row: Any, item: Any, version: Any) -> None:
    catalog = getattr(services, "catalog", None)
    cache = getattr(catalog, "index_cache", None) if catalog is not None else None
    if snapshot is None and cache is None:
        return
    checks = [
        (
            getattr(item, "id", ""),
            getattr(version, "v", ""),
            getattr(getattr(version, "sig", None), "key_id", "") or "",
        ),
        (
            getattr(row, "item_id", ""),
            getattr(row, "version", ""),
            getattr(row, "publisher_key_id", "") or "",
        ),
    ]
    for iid, ver, kid in checks:
        if not iid:
            continue
        revoked, reason, _since = item_revocation_status(
            item_id=iid,
            version=ver,
            publisher_key_id=kid,
            snapshot=snapshot,
            cache=cache,
        )
        if revoked:
            code = KEY_UNTRUSTED if reason == "key_revoked" else VERSION_REVOKED
            raise refuse_409(code, f"{iid!r} {ver!r} was revoked ({code})")


async def apply_version(
    request: Request,
    row,
    item,
    version,
    body: InstalledUpdateRequest,
    snapshot,
) -> InstalledItemView:
    services = request.app.state.services
    _check_revoked_for_update(services, snapshot, row, item, version)
    unlocked = carries_scripts(version)
    staging, staged = await fetch_and_stage(
        request, item, version, allow_scripts=unlocked
    )
    try:
        mismatch = check_digest(version.digest, staged.digest)
        if mismatch is not None:
            raise refuse_409(DIGEST_MISMATCH, mismatch.detail)

        body_sha, _size = await asyncio.to_thread(
            lambda: hash_file(resolve_manifest_path(row.kind, staged.path))
        )
        needs_consent = unlocked or await asyncio.to_thread(
            staged_plugin_declares_code, row.kind, staged.path
        )
        installed_dir = await asyncio.to_thread(_resolve_installed_dir, services, row)
        perm_diff = await asyncio.to_thread(
            compute_permission_diff, installed_dir, staged.path, row=row, version=version
        )
        if perm_diff.provenance.commit_sha_mismatch:
            raise refuse_409(
                "commit_sha_mismatch",
                f"{item.id!r} {version.v!r} commit_sha changed without a version bump",
                permission_diff=perm_diff.as_dict(),
            )
        mod_facts = (
            await catalog_mod_gates.gate_staged_mod(version, staged.path)
            if row.kind == KIND_MOD
            else None
        )
        consent_ok = consent_carried(
            row,
            body,
            body_sha,
            scripts_present=needs_consent,
            digest=staged.digest,
        )
        escalation_unaccepted = perm_diff.requires_reconsent and not bool(
            getattr(body.consent, "accept_permission_escalation", False)
        )
        if not consent_ok or escalation_unaccepted:
            if row.kind == KIND_CPLUG:
                mod_facts = await catalog_cplug_gates.gate_staged_cplug(request, item, staged.path, version)
            detail_msg = (
                f"{version.v} escalates permissions or execution capabilities; review the diff and re-consent"
                if perm_diff.requires_reconsent and consent_ok
                else (
                    f"{version.v} ships executable content, so an unchanged "
                    "SKILL.md is not consent to it; show the script list and "
                    "send the consent back with scripts accepted"
                )
                if needs_consent
                else None
            )
            raise consent_409(
                request,
                item,
                version,
                staged,
                body_sha,
                detail=detail_msg,
                diff=await update_diff(services, item, row, version, staged.path),
                permission_diff=perm_diff,
                mod_facts=mod_facts,
            )
        if row.kind == KIND_CPLUG and catalog_cplug_gates.version_requires_warning_ack(version):
            if not catalog_cplug_gates.flagged_ack_given(body.consent):
                raise catalog_cplug_gates.flagged_409(
                    version, body_sha=body_sha, digest=staged.digest
                )
        if mod_facts is not None:
            catalog_mod_gates.check_mod_consent(body.consent, mod_facts)

        async with _cplug_reload_lock(request, row):
            if row.kind == KIND_CPLUG:
                await catalog_cplug_gates.stop_before_update(request, row)
            try:
                updated = await asyncio.to_thread(
                    apply_update_now,
                    request,
                    row=row,
                    version=version,
                    staged=staged,
                    body_sha=body_sha,
                    expected_revision=body.expected_revision,
                )
            except Exception:
                if row.kind == KIND_CPLUG:
                    await catalog_cplug_gates.resume_after_failed_update(request, row)
                raise
            if row.kind == KIND_CPLUG:
                await asyncio.to_thread(catalog_cplug_gates.strip_grant_after_update, request, updated)
    finally:
        await asyncio.to_thread(discard_staging, staging)

    install_reporter.schedule_for(services, updated.item_id, updated.version)
    catalog = getattr(services, "catalog", None)
    cache = getattr(catalog, "index_cache", None) if catalog is not None else None
    view = installed_view(updated, snapshot, cache=cache) if cache is not None else installed_view(updated, snapshot)
    await asyncio.to_thread(annotate_watch, services, [updated], [view], force=True)
    return view
