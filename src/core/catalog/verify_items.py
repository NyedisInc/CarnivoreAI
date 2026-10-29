
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple

import structlog
from pydantic import ValidationError

from src.models.catalog import (
    CatalogItem,
    ItemVersion,
    PublisherEntry,
    is_reserved_name,
)
from src.core.skills.kinds import archive_root
from src.models.catalog_statement import release_statement

from .delegation import Delegation, delegated_key_for
from .log_safe import log_value
from .minisign import (
    MinisignFormatError,
    PublicKey,
    Signature,
    parse_public_key,
    verify,
)
from .revocation import version_subject
from .verify_types import (
    ITEM_SCHEMA_DETAIL_PREFIX,
    KEY_UNTRUSTED,
    NAME_RESERVED,
    SIGNATURE_INVALID,
    VERSION_REVOKED,
    ItemRefusal,
)

logger = structlog.get_logger(__name__)

MAX_REPORTED_ERRORS = 3


def errors_summary(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:MAX_REPORTED_ERRORS]:
        location = ".".join(str(piece) for piece in error.get("loc", ()))
        parts.append(f"{location or '<root>'}: {error.get('msg', 'invalid')}")
    return "; ".join(parts) or "invalid"


def report_key_impersonation(
    publishers: Dict[str, PublisherEntry],
    publisher_key: Optional[PublicKey],
) -> None:
    if publisher_key is None:
        return
    reported: Set[str] = set()
    for entry in publishers.values():
        for advertised in entry.keys:
            try:
                parsed = parse_public_key(advertised.pub)
            except MinisignFormatError:
                logger.warning(
                    "catalog_publisher_key_unreadable",
                    key_id=log_value(advertised.key_id),
                )
                continue
            if parsed.key_id != publisher_key.key_id:
                continue
            if parsed.raw != publisher_key.raw and parsed.key_id not in reported:
                reported.add(parsed.key_id)
                logger.warning(
                    "catalog_publisher_key_impersonated",
                    key_id=parsed.key_id,
                    consequence="advertising is ignored; trust is the pinned key",
                )


@dataclass(frozen=True)
class ItemVerdict:

    item: Optional[CatalogItem]
    trusted: bool
    refusal: Optional[ItemRefusal]
    version: Optional[ItemVersion] = None


def latest_version(item: CatalogItem) -> Optional[ItemVersion]:
    for version in item.versions:
        if version.v == item.latest:
            return version
    return None


def _refuse_item(item_id: str, code: str, detail: str) -> ItemVerdict:
    logger.warning(
        "catalog_item_refused",
        item_id=log_value(item_id),
        code=code,
        detail=detail,
    )
    return ItemVerdict(
        item=None,
        trusted=False,
        refusal=ItemRefusal(item_id=item_id, code=code, detail=detail),
    )


def duplicate_id_verdict(item_id: str) -> ItemVerdict:
    return _refuse_item(
        item_id,
        SIGNATURE_INVALID,
        f"{ITEM_SCHEMA_DETAIL_PREFIX} id is already claimed by an earlier item",
    )


def _verify_release(
    item: CatalogItem, version: ItemVersion, publisher_key: PublicKey,
) -> Optional[ItemVerdict]:
    try:
        statement = release_statement(
            kind=item.kind,
            publisher=item.publisher,
            name=item.name,
            version=version.v,
            repo=version.src.repo,
            path=version.src.path,
            commit=version.src.commit,
            digest=version.digest,
        )
    except ValueError as exc:
        return _refuse_item(
            item.id, SIGNATURE_INVALID, f"release statement fields: {exc}"
        )

    try:
        signature = Signature.from_index_fields(
            version.sig.key_id,
            version.sig.sig,
            version.sig.tc,
            version.sig.gsig,
        )
    except MinisignFormatError as exc:
        return _refuse_item(
            item.id, SIGNATURE_INVALID, f"release signature is malformed: {exc}"
        )

    try:
        ok = verify(
            statement, signature, publisher_key, expect_prehashed=True,
        )
    except MinisignFormatError as exc:
        return _refuse_item(
            item.id,
            SIGNATURE_INVALID,
            f"release signature could not be checked: {exc}",
        )
    if not ok:
        return _refuse_item(
            item.id, SIGNATURE_INVALID, "release statement does not verify"
        )
    try:
        archive_root(item.kind, item.publisher, item.name, version.src.path)
    except ValueError as exc:
        return _refuse_item(item.id, SIGNATURE_INVALID, f"release src.path: {exc}")
    return None


def verify_item(
    raw_item: Any,
    *,
    publisher_key: Optional[PublicKey],
    revoked_key_ids: Set[str],
    revoked_versions: Set[str],
    delegations: Tuple[Delegation, ...] = (),
) -> ItemVerdict:
    item_id = ""
    if isinstance(raw_item, dict) and isinstance(raw_item.get("id"), str):
        item_id = raw_item["id"]

    try:
        item = CatalogItem.model_validate(raw_item)
    except ValidationError as exc:
        return _refuse_item(
            item_id,
            SIGNATURE_INVALID,
            f"{ITEM_SCHEMA_DETAIL_PREFIX} {errors_summary(exc)}",
        )

    identity = f"{item.publisher}/{item.name}"
    if item.id != identity:
        return _refuse_item(
            item.id,
            SIGNATURE_INVALID,
            f"{ITEM_SCHEMA_DETAIL_PREFIX} id is not the signed {identity!r}",
        )

    if len({version.v for version in item.versions}) != len(item.versions):
        return _refuse_item(
            item.id,
            SIGNATURE_INVALID,
            f"{ITEM_SCHEMA_DETAIL_PREFIX} two versions share one version string",
        )

    if is_reserved_name(item.name, item.kind, item.publisher):
        return _refuse_item(
            item.id,
            NAME_RESERVED,
            f"name {item.name!r} is reserved by a harness",
        )

    version = latest_version(item)
    if version is None:
        return _refuse_item(
            item.id, SIGNATURE_INVALID, "latest version missing"
        )

    signing_key_id = version.sig.key_id.strip().upper()
    if signing_key_id in revoked_key_ids:
        return _refuse_item(item.id, KEY_UNTRUSTED, "key revoked")
    if version_subject(identity, version.v) in revoked_versions:
        return _refuse_item(item.id, VERSION_REVOKED, "version revoked")

    if publisher_key is not None and signing_key_id == publisher_key.key_id:
        signing_key: Optional[PublicKey] = publisher_key
    else:
        signing_key = delegated_key_for(delegations, item.publisher, signing_key_id)

    if signing_key is None:
        logger.info(
            "catalog_item_untrusted_key",
            item_id=item.id,
            signing_key_id=log_value(signing_key_id),
        )
        return ItemVerdict(
            item=item, trusted=False, refusal=None, version=version
        )

    refusal = _verify_release(item, version, signing_key)
    if refusal is not None:
        return refusal
    return ItemVerdict(item=item, trusted=True, refusal=None, version=version)
