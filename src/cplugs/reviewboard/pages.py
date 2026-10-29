
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.cplugs.reviewboard import service

DEFAULT_VIEWPORT = 1400
MAX_SLUG_NAME = 48
FALLBACK_SLUG_NAME = "page"


def title_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def slug_name(title: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:MAX_SLUG_NAME].strip("-") or FALLBACK_SLUG_NAME
    name, n = base, 1
    while name in taken:
        n += 1
        suffix = f"-{n}"
        name = base[:MAX_SLUG_NAME - len(suffix)].rstrip("-") + suffix
    return name


def taken_today(root: Path) -> set[str]:
    prefix = f"{datetime.now().astimezone():%Y%m%d}-"
    return {r["slug"][len(prefix):] for r in service.boards(root)["boards"] if r["slug"].startswith(prefix)}


def existing_board(root: Path, item_id: int, title: str) -> Optional[str]:
    want = title_key(title)
    rows = service.boards(root, item_id)["boards"]
    return next((r["slug"] for r in rows if not r.get("scratch") and title_key(r["title"]) == want), None)


def create_args(item_id: int, title: str, summary: str, html: str, taken: set[str]) -> Dict[str, Any]:
    return {"slug_name": slug_name(title, taken), "title": title.strip(), "task": {"item_id": item_id}, "summary": summary, "html": html,
            "viewport": DEFAULT_VIEWPORT, "request_review": False}


def revise_args(summary: str, html: str) -> Dict[str, Any]:
    return {"summary": summary, "html": html, "request_review": False}
