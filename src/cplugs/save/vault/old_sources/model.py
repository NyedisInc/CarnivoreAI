
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional

import structlog

from src.cplugs.save.vault.old_sources import names

logger = structlog.get_logger()

READ_BLOCK = 1 << 20


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Refusal:

    source: str
    locator: str
    reason: str


@dataclass
class Intake:

    refused: List[Refusal] = field(default_factory=list)
    skipped: List[Refusal] = field(default_factory=list)


@dataclass(frozen=True)
class Copy:

    source: str
    locator: str
    ident: names.Ident
    length: int
    sha256: str
    captured_epoch: float
    opener: Callable[[], Iterator[bytes]]

    @property
    def key(self) -> tuple:
        return (self.ident.family, self.ident.conv)


def measure(opener: Callable[[], Iterator[bytes]]) -> tuple:
    digest, total = hashlib.sha256(), 0
    for block in opener():
        digest.update(block)
        total += len(block)
    return total, digest.hexdigest()


def checked(intake: Intake, source: str, locator: str, ident: names.Ident, opener: Callable[[], Iterator[bytes]], captured: float, *,
            want_sha: Optional[str] = None, want_length: Optional[int] = None, errors: tuple = (OSError,), trust: bool = False) -> Optional[Copy]:
    if trust and want_sha and want_length is not None:
        return Copy(source, locator, ident, int(want_length), want_sha, captured, opener)
    try:
        length, sha = measure(opener)
    except errors as exc:
        intake.refused.append(Refusal(source, locator, f"unreadable: {type(exc).__name__}"))
        logger.warning("old_source_unreadable", source=source, locator=locator, error=str(exc)[:200])
        return None
    if (want_sha and sha != want_sha) or (want_length is not None and length != want_length):
        intake.refused.append(Refusal(source, locator, "the bytes are not what the source recorded"))
        logger.warning("old_source_mismatch", source=source, locator=locator)
        return None
    return Copy(source, locator, ident, length, sha, captured, opener)
