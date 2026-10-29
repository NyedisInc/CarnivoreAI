
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from .minisign import PublicKey, parse_public_key

logger = structlog.get_logger(__name__)

_WARNED: frozenset[str] = frozenset()


def _warn_once(event: str, **context: object) -> None:
    global _WARNED
    if event in _WARNED:
        return
    _WARNED = _WARNED | {event}
    logger.warning(event, **context)

INDEX_PUBLIC_KEY: Optional[str] = (
    "RWToHYwCxY1tHuTdB6BZpA09AspX8hzX/fBkV0lSvRquib6mD0xTTFIG"
)

SPARE_INDEX_KEY_PLACEHOLDER: str = (
    "UNSET: the spare index key is not generated yet"
)

SPARE_INDEX_PUBLIC_KEY: str = SPARE_INDEX_KEY_PLACEHOLDER

PUBLISHER_PUBLIC_KEY: Optional[str] = (
    "RWSLc0Q76LhjNLhV3CcgMZGvNHCZYpVrWN5OFt09z2SImlq/lGQxBzVW"
)

MIN_INDEX_SERIAL: int = 3

MAX_SERIAL_JUMP: int = 1000

STALENESS_DAYS: int = 30


@dataclass(frozen=True)
class TrustRoot:

    index_key: Optional[PublicKey]
    publisher_key: Optional[PublicKey]
    min_index_serial: int = 0
    max_serial_jump: int = 1000
    staleness_days: int = 30
    spare_index_key: Optional[PublicKey] = None


class SpareIndexKeyError(ValueError):
    pass


def parse_spare_index_key(
    text: str,
    index_key: Optional[PublicKey],
    publisher_key: Optional[PublicKey] = None,
) -> Optional[PublicKey]:
    if text == SPARE_INDEX_KEY_PLACEHOLDER:
        return None
    spare = parse_public_key(text)
    if index_key is not None and spare.key_id == index_key.key_id:
        raise SpareIndexKeyError(
            f"the spare index key {spare.key_id} is the live index key"
        )
    if publisher_key is not None and spare.key_id == publisher_key.key_id:
        raise SpareIndexKeyError(
            f"the spare index key {spare.key_id} is the publisher key"
        )
    return spare


def production_trust_root() -> TrustRoot:
    index_key = (
        parse_public_key(INDEX_PUBLIC_KEY)
        if INDEX_PUBLIC_KEY is not None
        else None
    )
    publisher_key = (
        parse_public_key(PUBLISHER_PUBLIC_KEY)
        if PUBLISHER_PUBLIC_KEY is not None
        else None
    )

    missing = [
        name
        for name, key in (
            ("index", index_key), ("publisher", publisher_key),
        )
        if key is None
    ]
    if missing:
        logger.warning(
            "catalog_trust_root_unpinned",
            missing_keys=missing,
            consequence="every index is refused as signature_invalid",
        )

    spare_index_key = parse_spare_index_key(
        SPARE_INDEX_PUBLIC_KEY, index_key, publisher_key,
    )
    if spare_index_key is None:
        _warn_once(
            "catalog_spare_index_key_unpinned",
            consequence="no index-key-revoked statement can be accepted",
        )

    return TrustRoot(
        index_key=index_key,
        publisher_key=publisher_key,
        min_index_serial=MIN_INDEX_SERIAL,
        max_serial_jump=MAX_SERIAL_JUMP,
        staleness_days=STALENESS_DAYS,
        spare_index_key=spare_index_key,
    )
