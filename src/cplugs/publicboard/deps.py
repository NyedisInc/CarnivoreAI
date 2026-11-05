
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Protocol, Sequence, Tuple


class PublicReadError(Exception):
    pass


class Unavailable(PublicReadError):
    pass


class BoardMissing(PublicReadError):
    pass


class Unscannable(PublicReadError):
    pass


class LinkRow(Protocol):

    id: str
    board: str
    revision: str
    mode: str
    expires_at: int
    content_sha256: str


class CheckResult(Protocol):

    state: str
    link: Optional[LinkRow]


class RevisionRead(Protocol):

    revision: str
    latest: str
    texts: Tuple[str, ...]
    projection: Mapping[str, object]
    page: Optional[bytes]


@dataclass(frozen=True)
class ReadDeps:

    check: Callable[[str], CheckResult]
    active: Callable[[str], Optional[LinkRow]]
    advance: Callable[[str, str, str], int]
    revision: Callable[[str, str, Optional[str]], Optional[RevisionRead]]
    matches: Callable[[LinkRow, Iterable[str]], bool]
    fingerprint: Callable[[Iterable[str]], str]
    scan: Callable[[Sequence[str]], Mapping[str, int]]
    mint_ticket: Callable[[Sequence[str]], str]
    open_ticket: Callable[[str], Optional[Tuple[str, ...]]]
