
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from src.cplugs.reviewboard import store
from src.cplugs.reviewboard.errors import BoardNotFound

LOOK_DIR = "looks"
NAME = re.compile(r"--oc-[a-z0-9-]{1,60}", re.ASCII)
MAX_ENTRIES = 4096
MAX_VALUE = 200
_SLUG = re.compile(r"[0-9]{8}-[a-z0-9-]{1,48}")


def _path(state_folder: Path, slug: str) -> Path:
    if not _SLUG.fullmatch(slug):
        raise BoardNotFound(f"no board {slug} under the boards folder")
    return Path(state_folder) / LOOK_DIR / f"{slug}.json"


def read(state_folder: Path, slug: str) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(_path(state_folder, slug).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    palette = doc.get("palette") if isinstance(doc, dict) else None
    ok = isinstance(doc, dict) and isinstance(doc.get("theme"), str) and isinstance(palette, dict) and len(palette) <= MAX_ENTRIES
    return {"theme": doc["theme"], "palette": palette} if ok else None


def write(state_folder: Path, slug: str, theme: Optional[str], palette: Optional[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    path = _path(state_folder, slug)
    with store.locked(state_folder, f"{slug}.look"):
        if theme is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return None
        kept = {"theme": theme, "palette": palette or {}}
        path.parent.mkdir(parents=True, exist_ok=True)
        store.write_atomic(path, json.dumps(kept, ensure_ascii=False).encode("utf-8"))
        return kept
