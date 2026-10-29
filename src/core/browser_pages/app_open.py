
from __future__ import annotations

from typing import Any, Dict, Optional

from src.core import row_looks
from src.core.browser_pages import open_pages, page_tab, select


def label_of(asked: str, own: str) -> str:
    return (asked.strip() or own.strip() or "page")[:select.MAX_TITLE]


def page_info(page: open_pages.OpenPage, src: str | None) -> Dict[str, Any]:
    return {"id": page.id, "key": page.key, "frame": page.frame, "title": page.title, "opened_at": page.opened_at, "src": src}


def open_app_page(url: str, title: str = "", color: Optional[str] = None, icon: Optional[str] = None) -> Dict[str, Any]:
    page = page_tab.app_page(url)
    stored = open_pages.open_page(page["key"], page["frame"], label_of(title, page_tab.app_title(page["src"])), ref=None, src=page["src"])
    row_looks.apply_on_open(stored.id, color, icon)
    return {"page": page_info(stored, page["src"]), "select": select.select_page(stored.id, stored.title)}
