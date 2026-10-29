
from __future__ import annotations

from typing import Any, List, Tuple

import structlog
from fastapi import HTTPException, Request

from src.api.catalog_install_support import refuse_409
from src.api.catalog_views import find_item, installed_view
from src.core.catalog.index_cache import IndexSnapshot
from src.core.skills import kinds
from src.core.skills.install_types import (
    DIGEST_MISMATCH,
    LOADOUT_MANIFEST_INVALID,
    LOADOUT_MEMBER_UNKNOWN,
)
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL
from src.core.skills.loadout_manifest import (
    LoadoutManifestInvalid,
    read_loadout_manifest,
)
from src.core.skills.loadout_members import (
    LoadoutRefusal,
    MemberOutcome,
    ResolvedMember,
    is_complete,
    refused_members,
    resolve_members,
)
from src.models.catalog import CatalogItem, review_instructions_details, review_writes_instructions
from src.models.catalog_api import (
    InstalledItemView,
    LoadoutMemberPreview,
    LoadoutMemberView,
)

logger = structlog.get_logger()


def is_loadout(kind: str) -> bool:
    return kind == kinds.KIND_LOADOUT


def ensure_loadouts_root(request: Request) -> None:
    roots = request.app.state.services.install_roots
    for target in roots.targets_for(kinds.KIND_LOADOUT, SCOPE_GLOBAL, None):
        target.leaf_dir.mkdir(parents=True, exist_ok=True)


def ensure_cplug_root(request: Request) -> None:
    roots = request.app.state.services.install_roots
    for target in roots.targets_for(kinds.KIND_CPLUG, SCOPE_GLOBAL, None):
        target.leaf_dir.mkdir(parents=True, exist_ok=True)


def _refuse_loadout(refusal: LoadoutRefusal) -> HTTPException:
    logger.info(
        "loadout_refused",
        code=refusal.code,
        member=refusal.item_id,
    )
    return refuse_409(refusal.code, refusal.detail)


def resolved_members(
    request: Request, item: CatalogItem, staged: Any, snapshot: IndexSnapshot
) -> Tuple[ResolvedMember, ...]:
    try:
        manifest = read_loadout_manifest(staged.path, own_id=item.id)
    except LoadoutManifestInvalid as exc:
        logger.info(
            "loadout_manifest_invalid", item_id=item.id, detail=exc.detail
        )
        raise refuse_409(LOADOUT_MANIFEST_INVALID, exc.detail)

    verdict = resolve_members(
        manifest,
        lookup=lambda item_id: find_item(snapshot, item_id),
        unknown_code=LOADOUT_MEMBER_UNKNOWN,
        digest_code=DIGEST_MISMATCH,
    )
    if isinstance(verdict, LoadoutRefusal):
        raise _refuse_loadout(verdict)
    return verdict


def member_previews(
    request: Request, resolved: Tuple[ResolvedMember, ...]
) -> List[LoadoutMemberPreview]:
    services = request.app.state.services
    with services.catalog.ledger() as ledger:
        rows = {
            member.item.id: ledger.find(
                member.item.id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH
            )
            for member in resolved
        }
    previews: List[LoadoutMemberPreview] = []
    for member in resolved:
        row = rows.get(member.item.id)
        details, more = review_instructions_details(member.version.review)
        previews.append(
            LoadoutMemberPreview(
                item_id=member.item.id,
                version=member.version.v,
                kind=member.item.kind,
                title=member.item.card.title,
                scripts=member.version.scripts,
                installed=row is not None and row.version == member.version.v,
                instructions_write=review_writes_instructions(
                    member.version.review
                ),
                instructions_details=details,
                instructions_more=more,
            )
        )
    return previews


def record_members(
    request: Request, install_id: str, outcomes: Tuple[MemberOutcome, ...]
) -> None:
    services = request.app.state.services
    with services.catalog.loadouts() as ledger:
        ledger.record(install_id, outcomes)


def member_views(outcomes: Tuple[MemberOutcome, ...]) -> List[LoadoutMemberView]:
    return [
        LoadoutMemberView(
            item_id=outcome.item_id,
            version=outcome.version,
            state=outcome.state,
            code=outcome.code,
            detail=outcome.detail,
            install_id=outcome.install_id,
        )
        for outcome in outcomes
    ]


def loadout_view(
    row: Any, snapshot: IndexSnapshot, outcomes: Tuple[MemberOutcome, ...]
) -> InstalledItemView:
    view = installed_view(row, snapshot)
    view.members = member_views(outcomes)
    view.complete = is_complete(outcomes)
    if not view.complete:
        logger.warning(
            "loadout_installed_partial",
            item_id=row.item_id,
            install_id=row.install_id,
            refused=list(refused_members(outcomes)),
        )
    return view


def stored_member_views(
    request: Request, install_id: str
) -> List[LoadoutMemberView]:
    services = request.app.state.services
    with services.catalog.loadouts() as ledger:
        rows = ledger.members(install_id)
    return [
        LoadoutMemberView(
            item_id=row.item_id,
            version=row.version,
            state=row.state,
            detail=row.detail,
            install_id=row.member_install_id,
        )
        for row in rows
    ]


def removable_members(request: Request, row: Any) -> List[str]:
    if not is_loadout(row.kind):
        return []
    services = request.app.state.services
    with services.catalog.loadouts() as ledger:
        offered = ledger.unclaimed(row.install_id)
    return [member.item_id for member in offered]
