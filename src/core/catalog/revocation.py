
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import structlog

from src.models.catalog import Revocations, RevokedVersion
from src.models.catalog_names import RESERVED_CLAIM_HANDLES, is_first_party_publisher

from .delegation import Delegation, delegated_key_for
from .log_safe import log_value
from .minisign import MinisignFormatError, PublicKey, parse_signature, verify

logger = structlog.get_logger(__name__)

REVOKE_STATEMENT_HEADER = "carnivore-revoke-v1"

KIND_KEY = "key"
KIND_VERSION = "version"

VERSION_SUBJECT_SEPARATOR = "@"


@dataclass(frozen=True)
class RevocationRef:

    kind: str
    subject: str
    since: str


def version_subject(item_id: str, version: str) -> str:
    return f"{item_id}{VERSION_SUBJECT_SEPARATOR}{version}"


def revoke_statement(*, kind: str, subject: str, since: str) -> bytes:
    if kind not in (KIND_KEY, KIND_VERSION):
        raise ValueError(f"revocation kind must be key or version, got {kind!r}")
    fields = {"kind": kind, "subject": subject, "since": since}
    for field_name, value in fields.items():
        if not value:
            raise ValueError(f"revocation statement field {field_name} is empty")
        if "\n" in value or "\r" in value:
            raise ValueError(
                f"revocation statement field {field_name} contains a line break"
            )

    lines = [REVOKE_STATEMENT_HEADER, *fields.values()]
    return ("".join(f"{line}\n" for line in lines)).encode("utf-8")


def _ignore(kind: str, subject: str, reason: str) -> None:
    logger.warning(
        "catalog_revocation_unverifiable",
        revocation_kind=kind,
        subject=log_value(subject),
        reason=reason,
    )


def _verified_ref(
    *,
    kind: str,
    subject: str,
    since: str,
    statement: str,
    signature_text: str,
    publisher_key: PublicKey,
) -> Optional[RevocationRef]:
    try:
        expected = revoke_statement(kind=kind, subject=subject, since=since)
    except ValueError as exc:
        _ignore(kind, subject, f"fields cannot form a statement: {exc}")
        return None

    if statement.encode("utf-8") != expected:
        _ignore(kind, subject, "carried statement is not the one these fields name")
        return None

    try:
        signature = parse_signature(signature_text)
    except MinisignFormatError as exc:
        _ignore(kind, subject, f"signature is malformed: {exc}")
        return None

    try:
        ok = verify(
            expected, signature, publisher_key, expect_prehashed=True,
        )
    except MinisignFormatError as exc:
        _ignore(kind, subject, f"signature could not be checked: {exc}")
        return None
    if not ok:
        _ignore(kind, subject, "signature does not verify under the pinned key")
        return None

    return RevocationRef(kind=kind, subject=subject, since=since)


def _version_signing_key(
    entry: RevokedVersion, publisher_key: PublicKey, delegations: Sequence[Delegation],
) -> PublicKey:
    try:
        key_id = parse_signature(entry.sig).key_id
    except MinisignFormatError:
        return publisher_key
    if key_id == publisher_key.key_id:
        return publisher_key
    handle = entry.item.partition("/")[0]
    if is_first_party_publisher(handle) or handle in RESERVED_CLAIM_HANDLES:
        return publisher_key
    return delegated_key_for(tuple(delegations), handle, key_id) or publisher_key


def verify_revocations(
    revocations: Revocations, publisher_key: Optional[PublicKey],
    delegations: Sequence[Delegation] = (),
) -> Tuple[Tuple[RevocationRef, ...], int]:
    if publisher_key is None:
        ignored = len(revocations.keys) + len(revocations.versions)
        if ignored:
            logger.warning(
                "catalog_revocations_unpinned",
                ignored=ignored,
                consequence="no publisher key is pinned, so nothing can be verified",
            )
        return ((), ignored)

    refs: List[RevocationRef] = []
    ignored = 0

    for entry in revocations.keys:
        ref = _verified_ref(
            kind=KIND_KEY,
            subject=entry.key_id,
            since=entry.since,
            statement=entry.statement,
            signature_text=entry.sig,
            publisher_key=publisher_key,
        )
        if ref is None:
            ignored += 1
        else:
            refs.append(ref)

    for entry in revocations.versions:
        ref = _verified_ref(
            kind=KIND_VERSION,
            subject=version_subject(entry.item, entry.version),
            since=entry.since,
            statement=entry.statement,
            signature_text=entry.sig,
            publisher_key=_version_signing_key(entry, publisher_key, delegations),
        )
        if ref is None:
            ignored += 1
        else:
            refs.append(ref)

    return (tuple(refs), ignored)
