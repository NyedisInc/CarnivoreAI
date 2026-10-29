
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException, Request

from src.api.catalog_consent import (
    carries_scripts,
    install_consent_satisfied,
    staged_plugin_declares_code,
)
from src.api.catalog_install_support import apply_now, fetch_and_stage, plan
from src.core.catalog import release_vouch
from src.core.skills.consent_via_ddl import CONSENT_SHEET
from src.core.skills.digest import hash_file
from src.core.skills.install_types import (
    ALREADY_INSTALLED,
    CONSENT_REQUIRED,
    LOADOUT_MEMBER_UNKNOWN,
    InstallPlan,
    InstallRefusal,
)
from src.core.skills.installer import discard_staging
from src.core.skills.kinds import manifest_name
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL
from src.core.skills.loadout_members import (
    MEMBER_ALREADY_PRESENT,
    MEMBER_INSTALLED,
    MEMBER_REFUSED,
    MemberOutcome,
    ResolvedMember,
)
from src.models.catalog_api import InstallConsent

logger = structlog.get_logger()


def _consent_for(
    consents: Optional[Dict[str, InstallConsent]], item_id: str
) -> Optional[InstallConsent]:
    if not consents:
        return None
    return consents.get(item_id)


async def _install_one(
    request: Request,
    member: ResolvedMember,
    consents: Optional[Dict[str, InstallConsent]],
    index_url: str,
    revoked: tuple,
) -> MemberOutcome:
    services = request.app.state.services
    item, version = member.item, member.version

    with services.catalog.ledger() as ledger:
        existing = ledger.find(item.id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
    if existing is not None:
        if existing.version == version.v:
            return MemberOutcome(
                item_id=item.id,
                version=version.v,
                state=MEMBER_ALREADY_PRESENT,
                install_id=existing.install_id,
            )
        return MemberOutcome(
            item_id=item.id,
            version=version.v,
            state=MEMBER_REFUSED,
            code=ALREADY_INSTALLED,
            detail=(
                f"{item.id!r} is installed at {existing.version!r} and this "
                f"loadout pins {version.v!r}; changing the version installed "
                "is an update, not an install"
            ),
            install_id=existing.install_id,
        )

    key = services.catalog.trust_root.publisher_key
    why = release_vouch.vouch(
        item, version, version.digest, revoked,
        publisher_key=key, pinned_key_id=key.key_id.strip().upper() if key is not None else None,
    )
    if why is not None:
        logger.warning("loadout_member_not_vouched", item_id=item.id, version=version.v, reason=why)
        return MemberOutcome(
            item_id=item.id,
            version=version.v,
            state=MEMBER_REFUSED,
            code=release_vouch.INSTALL_ROUTE_CODES[why],
            detail=f"{item.id!r} {version.v!r} failed the release check ({why}); nothing was fetched",
        )

    unlocked = carries_scripts(version)
    consent = _consent_for(consents, item.id)
    if unlocked and (consent is None or not consent.scripts):
        return MemberOutcome(
            item_id=item.id,
            version=version.v,
            state=MEMBER_REFUSED,
            code=CONSENT_REQUIRED,
            detail=(
                f"{item.id!r} ships executable content; consenting to this "
                "loadout is not consent to it. preview that item, show its "
                "script list, and send its own consent back"
            ),
        )

    try:
        staging, staged = await fetch_and_stage(
            request, item, version, allow_scripts=unlocked
        )
    except HTTPException as exc:
        return MemberOutcome(
            item_id=item.id,
            version=version.v,
            state=MEMBER_REFUSED,
            code=_code_of(exc),
            detail=f"{item.id!r} could not be fetched or extracted",
        )

    try:
        if unlocked or await asyncio.to_thread(
            staged_plugin_declares_code, item.kind, staged.path
        ):
            body_sha, _size = await asyncio.to_thread(
                hash_file, staged.path / manifest_name(item.kind)
            )
            if not install_consent_satisfied(
                consent, digest=staged.digest, body_sha=body_sha
            ):
                return MemberOutcome(
                    item_id=item.id,
                    version=version.v,
                    state=MEMBER_REFUSED,
                    code=CONSENT_REQUIRED,
                    detail=(
                        f"the consent sent for {item.id!r} does not name the "
                        "bytes that staged"
                    ),
                )

        verdict = await plan(
            request,
            item=item,
            version=version,
            staged=staged,
            scope=SCOPE_GLOBAL,
            project_path=None,
            choice=None,
            allow_scripts=unlocked,
        )
        if isinstance(verdict, InstallRefusal):
            return MemberOutcome(
                item_id=item.id,
                version=version.v,
                state=MEMBER_REFUSED,
                code=verdict.code,
                detail=verdict.detail,
            )
        if not isinstance(verdict, InstallPlan):  # pragma: no cover
            return MemberOutcome(
                item_id=item.id,
                version=version.v,
                state=MEMBER_REFUSED,
                code=LOADOUT_MEMBER_UNKNOWN,
                detail=f"{item.id!r} produced no plan and no refusal",
            )

        try:
            row = await asyncio.to_thread(
                apply_now, request, verdict, index_url, CONSENT_SHEET
            )
        except OSError as exc:
            logger.error(
                "loadout_member_install_failed",
                item_id=item.id,
                error=str(exc),
            )
            return MemberOutcome(
                item_id=item.id,
                version=version.v,
                state=MEMBER_REFUSED,
                code=LOADOUT_MEMBER_UNKNOWN,
                detail=f"{item.id!r} could not be written: {exc}",
            )
    finally:
        await asyncio.to_thread(discard_staging, staging)

    return MemberOutcome(
        item_id=item.id,
        version=version.v,
        state=MEMBER_INSTALLED,
        install_id=row.install_id,
    )


def _code_of(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code:
            return code
    return LOADOUT_MEMBER_UNKNOWN


async def install_members(
    request: Request,
    *,
    resolved: Tuple[ResolvedMember, ...],
    consents: Optional[Dict[str, InstallConsent]],
    index_url: str,
    snapshot: Any,
) -> Tuple[MemberOutcome, ...]:
    outcomes: List[MemberOutcome] = []
    cache = request.app.state.services.catalog.index_cache
    revoked = await asyncio.to_thread(cache.revoked_sets, snapshot.verified)
    for member in resolved:
        outcomes.append(
            await _install_one(request, member, consents, index_url, revoked)
        )
    return tuple(outcomes)
