
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.cplugs.reviewboard import store
from src.cplugs.reviewboard.errors import BoardNotFound, DraftStale
from src.cplugs.reviewboard.requests import DraftBody

TOPIC = "drafts"
DRAFT_DIR = "drafts"
_SLUG = re.compile(r"[0-9]{8}-[a-z0-9-]{1,48}")


def _path(state_folder: Path, slug: str) -> Path:
    if not _SLUG.fullmatch(slug):
        raise BoardNotFound(f"no board {slug} under the boards folder")
    return Path(state_folder) / DRAFT_DIR / f"{slug}.json"


def read(state_folder: Path, slug: str) -> Optional[Dict[str, Any]]:
    path = _path(state_folder, slug)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("rev"), int) else None


def write(state_folder: Path, slug: str, body: DraftBody) -> Dict[str, Any]:
    path = _path(state_folder, slug)
    with store.locked(state_folder, f"{slug}.draft"):
        current = read(state_folder, slug)
        if (current["rev"] if current else 0) != body.rev:
            raise DraftStale("the draft changed on another device; read it again", extra={"draft": current})
        draft = {**body.model_dump(mode="json", exclude={"rev"}), "rev": body.rev + 1,
                 "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        path.parent.mkdir(parents=True, exist_ok=True)
        store.write_atomic(path, json.dumps(draft, ensure_ascii=False).encode("utf-8"))
    return draft


def clear(state_folder: Path, slug: str, client_round_id: Optional[str] = None) -> bool:
    path = _path(state_folder, slug)
    with store.locked(state_folder, f"{slug}.draft"):
        current = read(state_folder, slug)
        if current is None or (client_round_id is not None and current.get("client_round_id") != client_round_id):
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True

