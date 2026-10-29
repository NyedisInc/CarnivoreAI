
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Union

import structlog

from src.core.skills.kinds import KIND_LOADOUT
from src.core.skills.loadout_manifest import LoadoutManifest, LoadoutMember
from src.models.catalog import CatalogItem, ItemVersion

logger = structlog.get_logger()

MEMBER_INSTALLED = "installed"

# nothing was written
MEMBER_ALREADY_PRESENT = "already_present"

MEMBER_REFUSED = "refused"

MEMBER_STATES: Tuple[str, ...] = (
    MEMBER_INSTALLED,
    MEMBER_ALREADY_PRESENT,
    MEMBER_REFUSED,
)


@dataclass(frozen=True)
class ResolvedMember:

    member: LoadoutMember
    item: CatalogItem
    version: ItemVersion


@dataclass(frozen=True)
class MemberOutcome:

    item_id: str
    version: str
    state: str
    code: Optional[str] = None
    detail: Optional[str] = None
    install_id: Optional[str] = None


@dataclass(frozen=True)
class LoadoutRefusal:

    code: str
    detail: str
    item_id: Optional[str] = None


Lookup = Callable[[str], Tuple[Optional[CatalogItem], bool]]


def _version_named(item: CatalogItem, wanted: str) -> Optional[ItemVersion]:
    for version in item.versions:
        if version.v == wanted:
            return version
    return None


def resolve_members(
    manifest: LoadoutManifest,
    *,
    lookup: Lookup,
    unknown_code: str,
    digest_code: str,
) -> Union[Tuple[ResolvedMember, ...], LoadoutRefusal]:
    resolved: list[ResolvedMember] = []
    for member in manifest.members:
        item, untrusted = lookup(member.item_id)
        if item is None:
            return LoadoutRefusal(
                code=unknown_code,
                detail=(
                    f"this loadout lists {member.item_id!r}, which this "
                    "catalog does not carry; the set cannot be installed "
                    "as a set"
                ),
                item_id=member.item_id,
            )
        if untrusted:
            return LoadoutRefusal(
                code=unknown_code,
                detail=(
                    f"this loadout lists {member.item_id!r}, which is "
                    "signed by a key this app does not pin"
                ),
                item_id=member.item_id,
            )
        if item.kind == KIND_LOADOUT:
            return LoadoutRefusal(
                code=unknown_code,
                detail=(
                    f"this loadout lists {member.item_id!r}, which is "
                    "itself a loadout; a loadout lists items, never other "
                    "loadouts"
                ),
                item_id=member.item_id,
            )

        version = _version_named(item, member.version)
        if version is None:
            return LoadoutRefusal(
                code=unknown_code,
                detail=(
                    f"this loadout pins {member.item_id!r} at "
                    f"{member.version!r}, which this catalog no longer "
                    "carries"
                ),
                item_id=member.item_id,
            )

        if version.digest != member.digest:
            return LoadoutRefusal(
                code=digest_code,
                detail=(
                    f"this loadout lists {member.item_id!r} "
                    f"{member.version!r} with a digest the catalog does "
                    "not agree with, so the list names bytes its own "
                    "publisher did not sign"
                ),
                item_id=member.item_id,
            )

        resolved.append(
            ResolvedMember(member=member, item=item, version=version)
        )

    logger.debug("loadout_members_resolved", members=len(resolved))
    return tuple(resolved)


def is_complete(outcomes: Tuple[MemberOutcome, ...]) -> bool:
    if not outcomes:
        return False
    return all(
        outcome.state in (MEMBER_INSTALLED, MEMBER_ALREADY_PRESENT)
        for outcome in outcomes
    )


def refused_members(outcomes: Tuple[MemberOutcome, ...]) -> Tuple[str, ...]:
    return tuple(
        outcome.item_id
        for outcome in outcomes
        if outcome.state == MEMBER_REFUSED
    )
