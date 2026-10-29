
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from src.cplugs.reviewboard import viewer
from src.cplugs.reviewboard.errors import BadRequest, BoardNotFound
from src.cplugs.sdk import browser_pages

POPOUT_PATH = "/static/popout.html"
TAB = "reviewboard"


def page_path(slug: str, revision: Optional[str] = None) -> str:
    query = {"tab": TAB, "board": slug, **({"rev": revision} if revision else {})}
    return f"{POPOUT_PATH}?{urlencode(query)}"


def style_board(slug: str, color: Optional[str], icon: Optional[str]) -> None:
    browser_pages.style_page(page_path(slug), color, icon)


def open_board(root: Path, slug: str, revision: Optional[str] = None, color: Optional[str] = None, icon: Optional[str] = None) -> Dict[str, Any]:
    sidecar = viewer.load_sidecar(root, slug)
    live_draft = revision == viewer.DRAFT_ID and sidecar.live is not None
    if revision is not None and not live_draft and not any(r.id == revision for r in sidecar.revisions):
        raise BoardNotFound(f"board {slug} has no revision {revision}")
    try:
        path = page_path(slug, revision)
        if revision is not None and color is None and icon is None and browser_pages.page_look(path) is None:
            color, icon = browser_pages.page_look(page_path(slug)) or (None, None)
        return browser_pages.open_app_page(path, sidecar.board.title, color, icon)
    except browser_pages.AppPageRefused as exc:
        raise BadRequest(f"the board page cannot be opened: {exc}") from exc
