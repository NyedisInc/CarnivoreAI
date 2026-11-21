
from __future__ import annotations

from typing import List, Optional, Tuple

from src.core import row_looks
from src.core.browser_pages import open_pages, page_tab
from src.core.browser_pages.app_open import open_app_page
from src.core.browser_pages.page_tab import AppPageRefused
from src.core.browser_pages.resolvers import PageNotFound, ResolvedPage, register, unregister
from src.core.row_looks import RowLookRefused, checked as check_look
from src.core.row_looks.palette import COLORS, ICONS

__all__ = ["AppPageRefused", "COLORS", "ICONS", "OpenPage", "PageNotFound", "ResolvedPage", "RowLookRefused", "check_look", "open_app_page",
           "open_artifact_rows", "page_look", "register", "replace_row", "style_page", "unregister"]

OpenPage = open_pages.OpenPage


def _row_id(url: str) -> str:
    return open_pages.page_id(page_tab.app_page(url)["key"])


def style_page(url: str, color: Optional[str], icon: Optional[str]) -> None:
    row_looks.apply_on_open(_row_id(url), color, icon)


def page_look(url: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
    held = row_looks.listing().get(_row_id(url))
    return None if held is None else (held.color, held.icon)


def open_artifact_rows() -> List[OpenPage]:
    return [p for p in open_pages.listing() if p.ref is not None and p.key.startswith(f"{page_tab.KIND_ARTIFACT}:")]


def replace_row(row_id: str, url: str, title: str) -> bool:
    page = page_tab.app_page(url)
    old = open_pages.get(row_id)
    if old is None:
        return False
    held = row_looks.listing().get(row_id)
    stored = open_pages.open_page(page["key"], page["frame"], title, ref=None, src=page["src"])
    if held is not None:
        row_looks.apply_on_open(stored.id, held.color, held.icon)
    open_pages.close(row_id)
    return True
