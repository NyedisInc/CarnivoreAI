
from __future__ import annotations

from typing import Optional, Protocol

from src.cplugs.sdk import ports

PORT = "reviewboard.attachments"


class BoardFiles(Protocol):

    def lists_file(self, item_id: int, file_id: str) -> bool:
        pass


def port() -> Optional[BoardFiles]:
    return ports.get(PORT)
