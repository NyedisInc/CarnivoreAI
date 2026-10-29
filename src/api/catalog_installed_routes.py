
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_install_support import (
    fetch_and_stage,
    refuse_409,
    resolve_item,
)
from src.api.catalog_consent import (
    carries_scripts,
    staged_plugin_declares_code,
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
from src.api.catalog_views import installed_view
from src.core.catalog import install_reporter
from src.core.catalog.verify import check_digest
from src.core.skills.digest import hash_file
from src.core.skills.install_types import ALREADY_INSTALLED, DIGEST_MISMATCH
from src.core.skills.installer import discard_staging
from src.core.skills.targets import TrashFolderIsLink
from src.core.skills.kinds import KIND_CPLUG, KIND_MOD, manifest_name
from src.core.skills.updates import update_available
from src.models.catalog_api import (
    InstalledItemView,
    InstalledPatchRequest,
    InstalledUpdateRequest,
    UninstallResponse,
)

router = APIRouter(tags=["catalog"])


@router.delete(
    "/catalog/installed/{install_id}",
    response_model=UninstallResponse,
    dependencies=[Depends(require_auth)],
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
    dependencies=[Depends(require_auth)],
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
    view = installed_view(row, snapshot)
    await asyncio.to_thread(annotate_watch, services, [row], [view])
    return view


@router.post(
    "/catalog/installed/{install_id}/update",
    response_model=InstalledItemView,
    dependencies=[Depends(require_auth)],
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
    item, version = resolve_item(snapshot, row.item_id)
    if not update_available(row, version):
        raise refuse_409(
            ALREADY_INSTALLED,
            f"{row.item_id!r} is up to date at {row.version!r}",
        )
    return await apply_version(request, row, item, version, body, snapshot)


async def apply_version(
    request: Request,
    row,
    item,
    version,
    body: InstalledUpdateRequest,
    snapshot,
) -> InstalledItemView:
    services = request.app.state.services
    unlocked = carries_scripts(version)
    staging, staged = await fetch_and_stage(
        request, item, version, allow_scripts=unlocked
    )
    try:
        mismatch = check_digest(version.digest, staged.digest)
        if mismatch is not None:
            raise refuse_409(DIGEST_MISMATCH, mismatch.detail)

        body_sha, _size = await asyncio.to_thread(
            hash_file, staged.path / manifest_name(row.kind)
        )
        needs_consent = unlocked or await asyncio.to_thread(
            staged_plugin_declares_code, row.kind, staged.path
        )
        mod_facts = (
            await catalog_mod_gates.gate_staged_mod(version, staged.path)
            if row.kind == KIND_MOD
            else None
        )
        if not consent_carried(
            row,
            body,
            body_sha,
            scripts_present=needs_consent,
            digest=staged.digest,
        ):
            if row.kind == KIND_CPLUG:
                mod_facts = await catalog_cplug_gates.gate_staged_cplug(request, item, staged.path, version)
            raise consent_409(
                request,
                item,
                version,
                staged,
                body_sha,
                detail=(
                    f"{version.v} ships executable content, so an unchanged "
                    "SKILL.md is not consent to it; show the script list and "
                    "send the consent back with scripts accepted"
                )
                if needs_consent
                else None,
                diff=await update_diff(services, item, row, version, staged.path),
                mod_facts=mod_facts,
            )
        if mod_facts is not None:
            catalog_mod_gates.check_mod_consent(body.consent, mod_facts)

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
    view = installed_view(updated, snapshot)
    await asyncio.to_thread(annotate_watch, services, [updated], [view], force=True)
    return view
