
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from src.cplugs.devwidgetlab.drafts import starter, store
from src.cplugs.devwidgetlab.errors import DraftExists, DraftInvalid

WIDGETS_JSON = Path("src") / "data" / "widgets.json"
MAX_SUFFIX = 99


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")


def declared_widget_ids(repo: Path) -> Set[str]:
    try:
        return {row["id"] for row in json.loads((repo / WIDGETS_JSON).read_text(encoding="utf-8"))["widgets"]}
    except (OSError, ValueError, KeyError) as exc:
        raise DraftInvalid(f"the widget declarations are unreadable: {type(exc).__name__}") from exc


def create_new(storage_path: Path, name: str, what: str, hosts: List[str], sizes: List[str], category: str) -> Dict[str, Any]:
    repo = store.require_checkout(storage_path)
    starter.check_new_request(name, hosts, sizes, category)
    slug = store.check_slug(slugify(name))
    widget = f"core.{slug}"
    if widget in declared_widget_ids(repo):
        raise DraftExists(f"{widget} is already a widget")
    folder = store.create_record(storage_path, slug, "new", widget, name)
    try:
        starter.write_new(folder, slug, name.strip(), what, hosts, sizes, category)
    except DraftInvalid:
        _abandon(storage_path, slug)
        raise
    return store.summary(folder)


def create_revision(storage_path: Path, widget: str, name: str, change: str, context: Dict[str, Any]) -> Dict[str, Any]:
    repo = store.require_checkout(storage_path)
    manifest = widget.split(":", 1)[0]
    if manifest not in declared_widget_ids(repo):
        raise DraftInvalid(f"{widget} is not a declared widget")
    base = slugify(name) or f"{manifest.split('.', 1)[-1]}-revision"
    slug = _free_slug(storage_path, base)
    folder = store.create_record(storage_path, slug, "revision", widget, name.strip() or f"revision of {widget}")
    starter.write_revision_note(folder, slug, widget, name.strip() or slug, change, context)
    return store.summary(folder)


def _free_slug(storage_path: Path, base: str) -> str:
    store.check_slug(base)
    for n in range(1, MAX_SUFFIX + 1):
        slug = base if n == 1 else f"{base[:36]}-{n}"
        if not store.draft_dir(storage_path, slug).exists():
            return slug
    raise DraftExists(f"too many drafts named like {base}")


def _abandon(storage_path: Path, slug: str) -> None:
    store.discard(storage_path, slug)
