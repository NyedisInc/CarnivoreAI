
from __future__ import annotations

import json
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

HOLD_KEY = "ref_hold"
_cache: dict[str, Any] = {"sig": None, "ids": frozenset()}


def _state_path() -> Any:
    from pathlib import Path

    from src.config import settings

    return Path(settings.get_state_dir()) / "pack" / "skills-state.json"


def held_ids() -> frozenset:
    path = _state_path()
    try:
        info = path.stat()
    except OSError:
        _cache.update(sig=None, ids=frozenset())
        return _cache["ids"]
    sig = (str(path), info.st_mtime_ns, info.st_size)
    if sig == _cache["sig"]:
        return _cache["ids"]
    ids: frozenset = frozenset()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        doc = data.get("doc") if isinstance(data, dict) else None
        if isinstance(data, dict) and data.get(HOLD_KEY) is True and isinstance(doc, dict):
            refs = data.get("refs") if isinstance(data.get("refs"), dict) else {}
            ids = frozenset(r[2] for r in doc.get("warez", []) if isinstance(r, list) and len(r) > 4 and isinstance(r[2], str)
                            and isinstance(refs.get(r[2]), dict) and refs[r[2]].get("outcome") == "in sync"
                            and refs[r[2]].get("version") == r[4])
    except (OSError, ValueError) as exc:
        logger.warning("update_holds_unreadable", error=type(exc).__name__)
    _cache.update(sig=sig, ids=ids)
    return ids


def held(item_id: Optional[str]) -> bool:
    return item_id in held_ids()
