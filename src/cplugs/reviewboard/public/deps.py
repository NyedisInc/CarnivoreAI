
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


class CapSpent(PublicReadError):

    def __init__(self, which: str) -> None:
        super().__init__(which)
        self.which = which


class LinkRow(Protocol):

    id: str
    board: str
    revision: str
    mode: str
    expires_at: int
    content_sha256: str
    access: str
    theme: Optional[Mapping[str, str]]


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
    ticket_ttl_s: int = 300
    own_draft: Callable[[str, str, str], Optional[Mapping[str, object]]] = lambda link_id, key, revision: None
    follow: Callable[[Callable[[], None]], Callable[[], None]] = lambda listener: (lambda: None)
    latest: Callable[[str], Optional[str]] = lambda board: None
    served: Callable[[str, str], bool] = lambda link_id, revision: False
    board_theme: Callable[[str], Optional[Mapping[str, str]]] = lambda board: None
    served_revisions: Callable[[str], Sequence[str]] = lambda link_id: ()
    answered_revisions: Callable[[str, str], Sequence[str]] = lambda link_id, key: ()
    beat: Callable[[str, str, str], None] = lambda link_id, board, key: None


class StoredPost(Protocol):

    id: int
    duplicate: bool


@dataclass(frozen=True)
class WriteDeps:

    check: Callable[[str, str, str, Mapping[str, object]], Optional[Sequence[str]]]
    store: Callable[[str, str, str, str, Optional[str], Mapping[str, object], str, Optional[str]], StoredPost]
    save_draft: Callable[[str, str, str, str, Mapping[str, object]], bool]
    prune: Callable[[], int] = lambda: 0
