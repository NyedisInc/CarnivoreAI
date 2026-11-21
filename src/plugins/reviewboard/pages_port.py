
from __future__ import annotations

from src.plugins.reviewboard import opener
from src.plugins.sdk import board_pages, ports


class PagesPort:

    def page_path(self, slug: str) -> str:
        return opener.page_path(slug)


def register() -> None:
    ports.register(board_pages.PORT, PagesPort())


def unregister() -> None:
    ports.unregister(board_pages.PORT)
