
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Union

from src.core.catalog.fetch_stream import FetchRefusal
from src.core.catalog.verify_types import VerifiedIndex, VerifyRefusal


@dataclass(frozen=True)
class IndexSnapshot:

    verified: Optional[VerifiedIndex]
    refusal: Optional[Union[VerifyRefusal, FetchRefusal]]
    as_of: Optional[datetime]
    degraded: bool
    fetched_at: Optional[float]
    stale: bool


EMPTY_SNAPSHOT = IndexSnapshot(
    verified=None,
    refusal=None,
    as_of=None,
    degraded=False,
    fetched_at=None,
    stale=True,
)


def serial_of(snapshot: IndexSnapshot) -> Any:
    return None if snapshot.verified is None else snapshot.verified.serial


def content_fingerprint(snapshot: IndexSnapshot) -> str:
    refusal = snapshot.refusal
    parts = (
        snapshot.verified,
        None if refusal is None else (refusal.code, refusal.detail),
        snapshot.degraded,
    )
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()
