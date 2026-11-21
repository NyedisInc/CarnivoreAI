
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple

from src.plugins.sdk import ports

PORT = "reviewboard.public"


class PublicBoardMissing(LookupError):
    pass


class PublicBoardUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RevisionTexts:

    slug: str
    revision: str
    latest: str
    title: str
    texts: Tuple[str, ...]


@dataclass(frozen=True)
class PublicRevision:

    slug: str
    revision: str
    latest: str
    texts: Tuple[str, ...]
    projection: Mapping[str, Any]
    page: Optional[bytes] = None


class PublicBoards(Protocol):

    def revision_texts(self, slug: str, revision: Optional[str] = None) -> RevisionTexts:
        pass

    def public_revision(self, slug: str, revision: str, view: Optional[str] = None) -> PublicRevision:
        pass

    def latest(self, slug: str) -> str:
        pass

    def board_theme(self, slug: str) -> Optional[Dict[str, str]]:
        pass

    def check_post(self, slug: str, revision: str, kind: str, body: Mapping[str, Any]) -> List[str]:
        pass

    def follow(self, listener: Callable[[], None]) -> Callable[[], None]:
        pass

    async def forward(self, slug: str, text: str, revisions: List[str]) -> Dict[str, Any]:
        pass


def port() -> Optional[PublicBoards]:
    return ports.get(PORT)
