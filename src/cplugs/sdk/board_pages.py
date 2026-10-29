
from __future__ import annotations

from typing import Optional, Protocol

from src.cplugs.sdk import ports

PORT = "reviewboard.pages"


class BoardPagesPort(Protocol):

    def page_path(self, slug: str) -> str:
        pass


def get() -> Optional[BoardPagesPort]:
    return ports.get(PORT)


__all__ = ["PORT", "BoardPagesPort", "get"]
