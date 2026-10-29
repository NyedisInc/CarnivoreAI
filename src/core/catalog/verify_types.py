
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Tuple

from pydantic import Field

from src.models.catalog import CatalogItem, IndexDocument

from .revocation import RevocationRef

SIGNATURE_INVALID = "signature_invalid"

INDEX_ROLLBACK = "index_rollback"

INDEX_SERIAL_JUMP = "index_serial_jump"

KEY_UNTRUSTED = "key_untrusted"

VERSION_REVOKED = "version_revoked"

NAME_RESERVED = "name_reserved"

DIGEST_MISMATCH = "digest_mismatch"

SCRIPTS_NOT_SUPPORTED = "scripts_not_supported"

INDEX_NOT_JSON = "index_not_json"

ITEM_SCHEMA_DETAIL_PREFIX = "item schema:"


class IndexEnvelope(IndexDocument):

    items: List[Any] = Field(default_factory=list)


@dataclass(frozen=True)
class VerifyRefusal:

    code: str
    detail: str


@dataclass(frozen=True)
class ItemRefusal:

    item_id: str
    code: str
    detail: str


@dataclass(frozen=True)
class VerifiedIndex:

    serial: int
    generated_at: datetime
    degraded: bool
    items: Tuple[CatalogItem, ...]
    untrusted_items: Tuple[CatalogItem, ...]
    refused: Tuple[ItemRefusal, ...]
    revocations: Tuple[RevocationRef, ...]
    index_key_id: str
    featured: Tuple[str, ...] = ()
