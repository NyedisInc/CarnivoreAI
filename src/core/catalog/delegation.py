
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple

import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from src.models.catalog import PublisherEntry
from src.models.catalog_names import RESERVED_CLAIM_HANDLES
from src.models.catalog_statement import ANY_HANDLE, parse_publisher_key_statement

from .log_safe import log_value
from .minisign import (
    MinisignFormatError,
    PublicKey,
    parse_public_key,
    parse_signature,
    verify,
)

logger = structlog.get_logger(__name__)


class _DelegationEntry(BaseModel):
    """The two carried fields of one delegation: the statement and its ``.minisig``."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    statement: str
    sig: str


@dataclass(frozen=True)
class Delegation:

    handle: str
    key: PublicKey
    custody: str


def _skip(reason: str) -> None:
    logger.warning("catalog_delegation_ignored", reason=reason)


def _verified(raw: Any, publisher_key: PublicKey) -> Optional[Delegation]:
    try:
        entry = _DelegationEntry.model_validate(raw)
        statement = parse_publisher_key_statement(entry.statement)
    except (ValidationError, ValueError):
        _skip("entry is malformed or its statement is not canonical")
        return None
    try:
        key = parse_public_key(statement.pub)
        signature = parse_signature(entry.sig)
    except MinisignFormatError:
        _skip("key line or signature is malformed")
        return None
    if key.key_id != statement.key_id:
        logger.warning(
            "catalog_delegation_ignored",
            reason="claimed key id is not the id of the carried key",
            key_id=log_value(statement.key_id),
        )
        return None
    try:
        ok = verify(
            entry.statement.encode("utf-8"), signature, publisher_key,
            expect_prehashed=True,
        )
    except MinisignFormatError:
        _skip("signature could not be checked")
        return None
    if not ok:
        logger.warning(
            "catalog_delegation_ignored",
            reason="signature does not verify under the pinned key",
            key_id=log_value(statement.key_id),
        )
        return None
    return Delegation(handle=statement.handle, key=key, custody=statement.custody)


def verify_delegations(
    publishers: Mapping[str, PublisherEntry], publisher_key: Optional[PublicKey],
) -> Tuple[Delegation, ...]:
    if publisher_key is None:
        return ()
    found: List[Delegation] = []
    for entry in publishers.values():
        for raw in entry.delegations:
            delegation = _verified(raw, publisher_key)
            if delegation is not None:
                found.append(delegation)
    return tuple(found)


def delegated_key_for(
    delegations: Tuple[Delegation, ...], publisher: str, key_id: str,
) -> Optional[PublicKey]:
    wanted = key_id.strip().upper()
    for delegation in delegations:
        if delegation.key.key_id != wanted:
            continue
        if delegation.handle == publisher:
            return delegation.key
        if (
            delegation.handle == ANY_HANDLE
            and delegation.custody == "catalog"
            and publisher not in RESERVED_CLAIM_HANDLES
        ):
            return delegation.key
    return None
