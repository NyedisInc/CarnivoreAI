
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException, Request

from src.api.catalog_views import find_item, latest_version
from src.core.catalog.archive_client import fetch_archive
from src.core.catalog.fetch_stream import FetchRefusal
from src.core.catalog.first_party import refuse_theme_code
from src.core.catalog.index_cache import IndexSnapshot
from src.core.catalog.verify_types import KEY_UNTRUSTED
from src.core.live_install_roots import HARNESS_CLAUDE, HARNESS_CODEX
from src.core import resource_push
from src.core.resource_push import topics as resource_topics
from src.core.skills.install_plan import plan_install
from src.core.skills.install_types import (
    PROJECT_PATH_INVALID,
    STALE_REVISION,
    InstallRefusal,
)
from src.core.skills.installer import (
    STAGING_BUSY,
    StagingBusy,
    apply_install,
    discard_staging,
    staging_root_for,
)
from src.core.skills.kinds import KIND_CPLUG, KIND_THEME
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.core.skills.plan_tokens import StagedPlan
from src.core.skills.project_scope import (
    ProjectPathRefused,
    resolve_project_path,
)
from src.core.skills.stage import stage_archive
from src.core.skills.validate import SCRIPTS_NOT_SUPPORTED, ArchiveRefused
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_api import InstallRequest, NameTakenChoice

logger = structlog.get_logger()

ARCHIVE_NAME = "archive.tar.gz"

STAGED_NAME = "skill"

def refuse_409(code: str, detail: str, **extra: Any) -> HTTPException:
    body: Dict[str, Any] = {"code": code, "detail": detail}
    body.update(extra)
    return HTTPException(status_code=409, detail=body)


def resolve_item(
    snapshot: IndexSnapshot, item_id: str
) -> Tuple[CatalogItem, ItemVersion]:
    item, untrusted = find_item(snapshot, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"no catalog item {item_id!r}")
    if untrusted:
        raise refuse_409(
            KEY_UNTRUSTED,
            f"{item_id!r} is signed by a key this app does not pin",
        )
    version = latest_version(item)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"{item_id!r} carries no version named {item.latest!r}",
        )
    return item, version


async def scope_arguments(
    request: Request, body: InstallRequest
) -> Tuple[str, Optional[str]]:
    if body.scope == SCOPE_GLOBAL:
        if body.project_path:
            raise HTTPException(
                status_code=400, detail="a global install takes no project_path"
            )
        return SCOPE_GLOBAL, None
    if not body.project_path or not body.project_path.strip():
        raise HTTPException(
            status_code=400, detail="a project install requires a project_path"
        )

    services = request.app.state.services
    try:
        resolved = await asyncio.to_thread(
            resolve_project_path,
            body.project_path,
            roots=services.install_roots,
            state_dir=services.settings_reader.state_dir(),
        )
    except ProjectPathRefused as exc:
        logger.info(
            "skill_project_path_refused",
            scope=body.scope,
            detail=exc.detail,
        )
        raise refuse_409(PROJECT_PATH_INVALID, exc.detail)
    return body.scope, resolved


def choice_views(refusal: InstallRefusal) -> List[NameTakenChoice]:
    views: List[NameTakenChoice] = []
    for choice in refusal.choices:
        delta = choice.delta
        views.append(
            NameTakenChoice(
                choice=choice.action,
                name=choice.name,
                added=None if delta is None else delta.added,
                changed=None if delta is None else delta.changed,
                removed=None if delta is None else delta.removed,
                bytes_delta=None if delta is None else delta.byte_delta,
                against=None if delta is None else delta.against,
            )
        )
    return views


def discovery_listing(roots: Any) -> Tuple[str, ...]:
    names: Tuple[str, ...] = ()
    for harness in (HARNESS_CLAUDE, HARNESS_CODEX):
        names = names + tuple(roots.read_only_listing(harness))
    return names


def refuse_cplug_scripts(item: CatalogItem, version: ItemVersion) -> None:
    if item.kind == KIND_CPLUG and version.scripts > 0:
        raise refuse_409(
            SCRIPTS_NOT_SUPPORTED,
            f"{item.id!r} is a plugin and declares executable content; a plugin installs without scripts",
        )


def _stage_now(
    archive: Path,
    staged_dir: Path,
    *,
    item: CatalogItem,
    allow_scripts: bool,
    src_path: str | None = None,
) -> Any:
    staged = stage_archive(
        archive,
        staged_dir,
        publisher=item.publisher,
        name=item.name,
        kind=item.kind,
        allow_scripts=allow_scripts,
        src_path=src_path,
    )
    try:
        refuse_theme_code(item, staged.path)
    except ArchiveRefused:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise
    return staged


async def fetch_and_stage(
    request: Request,
    item: CatalogItem,
    version: ItemVersion,
    *,
    allow_scripts: bool = False,
) -> Tuple[Path, Any]:
    return await fetch_and_stage_with(
        request.app.state.services, item, version, allow_scripts=allow_scripts
    )


async def fetch_and_stage_with(
    services: Any,
    item: CatalogItem,
    version: ItemVersion,
    *,
    allow_scripts: bool = False,
) -> Tuple[Path, Any]:
    refuse_cplug_scripts(item, version)
    if item.kind == KIND_CPLUG:
        allow_scripts = False
    roots = services.install_roots
    try:
        staging = await asyncio.to_thread(staging_root_for, roots)
    except StagingBusy as exc:
        raise refuse_409(STAGING_BUSY, str(exc))

    try:
        archive = await fetch_archive(version, dest_path=staging / ARCHIVE_NAME)
        if isinstance(archive, FetchRefusal):
            raise HTTPException(
                status_code=502,
                detail={"code": archive.code, "detail": archive.detail},
            )
        staged = await asyncio.to_thread(
            _stage_now,
            archive,
            staging / STAGED_NAME,
            item=item,
            allow_scripts=allow_scripts,
            src_path=version.src.path,
        )
    except ArchiveRefused as exc:
        await asyncio.to_thread(discard_staging, staging)
        raise refuse_409(exc.code, exc.detail)
    except BaseException:
        await asyncio.to_thread(discard_staging, staging)
        raise
    return staging, staged


def plan_now(request: Request, **arguments: Any) -> Any:
    catalog = request.app.state.services.catalog
    with catalog.ledger() as ledger:
        return plan_install(ledger=ledger, **arguments)


async def plan(
    request: Request,
    *,
    item: CatalogItem,
    version: ItemVersion,
    staged: Any,
    scope: str,
    project_path: Optional[str],
    choice: Optional[str],
    allow_scripts: bool = False,
    harnesses: Optional[List[str]] = None,
    create_roots: bool = False,
) -> Any:
    roots = request.app.state.services.install_roots
    listing = await asyncio.to_thread(discovery_listing, roots)
    present = frozenset(await asyncio.to_thread(roots.present_harnesses))
    effective = present if harnesses is None else present & frozenset(harnesses)
    return await asyncio.to_thread(
        plan_now,
        request,
        item=item,
        version=version,
        staged=staged,
        scope=scope,
        project_path=project_path,
        roots=roots,
        discovery_listing=listing,
        choice=choice,
        allow_scripts=allow_scripts,
        harnesses=effective,
        create_roots=create_roots,
    )


def announce_theme_change(row: Any) -> None:
    if row.kind == KIND_THEME:
        resource_push.notify(resource_topics.THEMES)


def apply_now(
    request: Request, decided: Any, index_url: str, consent_via: str
) -> Any:
    services = request.app.state.services
    catalog = services.catalog
    with catalog.ledger() as ledger:
        row = apply_install(
            decided,
            ledger=ledger,
            roots=services.install_roots,
            clock=services.clock,
            source_index_url=index_url,
            publisher_key_id=catalog.publisher_key_id,
            consent_via=consent_via,
        )
    announce_theme_change(row)
    return row


async def discard_all(plans: List[StagedPlan]) -> None:
    for entry in plans:
        await asyncio.to_thread(discard_staging, entry.staging)


async def claim_staged(
    request: Request,
    body: InstallRequest,
    scope: str,
    project_path: Optional[str],
    version: ItemVersion,
) -> Optional[StagedPlan]:
    store = request.app.state.services.catalog.staged_plans
    claimed, expired = store.take(body.plan_token)
    await discard_all(expired)
    if claimed is None:
        return None
    matches = (
        claimed.item_id == body.item_id
        and claimed.scope == scope
        and (claimed.project_path or None) == (project_path or None)
    )
    if not matches:
        logger.info("skill_plan_token_mismatch", item_id=body.item_id)
        await asyncio.to_thread(discard_staging, claimed.staging)
        return None
    if claimed.version != version.v:
        logger.info(
            "skill_plan_token_version_moved",
            item_id=body.item_id,
            previewed=claimed.version,
            now=version.v,
        )
        await asyncio.to_thread(discard_staging, claimed.staging)
        raise refuse_409(
            STALE_REVISION,
            f"the catalog now names {version.v!r} for {body.item_id!r}; the "
            f"preview described {claimed.version!r}. preview again.",
        )
    return claimed
