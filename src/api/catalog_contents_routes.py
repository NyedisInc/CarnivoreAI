
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_consent import carries_scripts
from src.api.catalog_install_routes import _snapshot
from src.api.catalog_install_support import fetch_and_stage_with, refuse_409, resolve_item
from src.core.catalog.verify import check_digest
from src.core.skills.contents_view import ContentsView, build_view, default_cache, diff_views
from src.core.skills.ledger_types import InstalledItem
from src.core.skills.digest import digest_directory, digest_entries
from src.core.skills.records import SIDECAR_NAME
from src.core.skills.install_types import DIGEST_MISMATCH
from src.core.skills.installer import discard_staging
from src.core.skills.validate import ArchiveRefused
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_contents import ContentsFile, ContentsResponse, FileChange, UpdateDiff

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])


async def view_of_version(
    services: Any, item: CatalogItem, version: ItemVersion
) -> ContentsView:
    hit = default_cache.get(version.digest)
    if hit is not None:
        return hit
    staging, staged = await fetch_and_stage_with(
        services, item, version, allow_scripts=carries_scripts(version)
    )
    try:
        mismatch = check_digest(version.digest, staged.digest)
        if mismatch is not None:
            logger.warning("catalog_contents_digest_mismatch", item_id=item.id, version=version.v)
            raise refuse_409(DIGEST_MISMATCH, mismatch.detail)
        try:
            view = await asyncio.to_thread(build_view, staged.path, item.kind, version.digest)
        except (OSError, UnicodeDecodeError) as exc:
            raise refuse_409("contents_unreadable", type(exc).__name__)
        default_cache.put(view)
        return view
    finally:
        await asyncio.to_thread(discard_staging, staging)


@router.get(
    "/catalog/contents/{item_id:path}",
    response_model=ContentsResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_contents(request: Request, item_id: str) -> ContentsResponse:
    """The file list and SKILL.md text of a catalog item's signed latest version.

    Inputs: item_id (str) - ``<publisher>/<name>``.
    Output: ContentsResponse.
    Raises: 404 unknown item; 409 ``key_untrusted``, ``digest_mismatch`` (nothing
      is returned) or an archive refusal; 502 the tarball could not be fetched.
    """
    services = request.app.state.services
    snapshot = await _snapshot(request)
    item, version = resolve_item(snapshot, item_id)
    try:
        view = await view_of_version(services, item, version)
    except ArchiveRefused as exc:
        raise refuse_409(exc.code, exc.detail)
    return ContentsResponse(
        item_id=item.id,
        version=version.v,
        digest=view.digest,
        files=[ContentsFile(path=f.path, size=f.size, kind=f.kind) for f in view.files],
        total_bytes=view.total_bytes,
        body=view.manifest_text,
        body_truncated=view.manifest_truncated,
    )


def _installed_view(services: Any, item: CatalogItem, row: InstalledItem) -> Optional[ContentsView]:
    with services.catalog.ledger() as ledger:
        targets = ledger.targets(row.install_id)
    for target in targets:
        folder = Path(target.path)
        if not folder.is_dir() or folder.is_symlink():
            continue
        entries = [e for e in digest_directory(folder)[1] if e.relpath != SIDECAR_NAME]
        if digest_entries(entries) == row.digest:
            return build_view(folder, item.kind, row.digest, exclude=(SIDECAR_NAME,))
    return None


async def update_diff(
    services: Any,
    item: CatalogItem,
    row: InstalledItem,
    new_version: ItemVersion,
    staged_dir: Any,
) -> Optional[UpdateDiff]:
    old_version = next(
        (v for v in item.versions if v.v == row.version and v.digest == row.digest), None
    )
    try:
        if old_version is not None:
            old_view = await view_of_version(services, item, old_version)
        else:
            old_view = await asyncio.to_thread(_installed_view, services, item, row)
        if old_view is None:
            return None
        new_view = default_cache.get(new_version.digest)
        if new_view is None:
            new_view = await asyncio.to_thread(build_view, staged_dir, item.kind, new_version.digest)
            default_cache.put(new_view)
    except (HTTPException, ArchiveRefused, OSError, UnicodeDecodeError) as exc:
        logger.warning("catalog_update_diff_unavailable", item_id=item.id, error=type(exc).__name__)
        return None
    changes, unchanged = diff_views(old_view, new_view)
    return UpdateDiff(
        from_version=row.version,
        to_version=new_version.v,
        changes=[FileChange(**c) for c in changes],
        unchanged=unchanged,
    )
