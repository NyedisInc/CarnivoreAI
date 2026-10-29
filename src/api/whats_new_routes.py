
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query

from src.api.auth import require_auth
from src.api.features_routes import _index_path

logger = structlog.get_logger()

router = APIRouter(tags=["features"])

MAX_ENTRIES = 30

_MAX_SINCE_CHARS = 40


def _parse_time(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text or len(text) > _MAX_SINCE_CHARS:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _entry_time(change: dict[str, Any]) -> datetime | None:
    return _parse_time(str(change.get("landed_at") or "")) or _parse_time(str(change.get("date") or ""))


def _load_index() -> dict[str, Any] | None:
    path = _index_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("whats_new_index_unavailable", path=str(path), error=str(exc))
        return None
    return data if isinstance(data, dict) else None


def _shape(change: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    feature = next((catalog[f] for f in change.get("features", []) if f in catalog and catalog[f].get("where")), None)
    return {
        "type": change.get("type", ""),
        "summary": change.get("summary", ""),
        "landed_at": change.get("landed_at", ""),
        "feature": feature.get("name", "") if feature else "",
        "where": list(feature.get("where", [])) if feature else [],
        "how_to": list(feature.get("how_to", [])) if feature else [],
    }


@router.get("/whats-new", dependencies=[Depends(require_auth)])
async def get_whats_new(since: str = Query("", max_length=200)) -> dict[str, Any]:
    """Return the build mark and the user-visible changes newer than ``since``.
    """
    index = _load_index()
    if index is None:
        return {"available": False, "mark": "", "total": 0, "more": 0, "entries": []}
    changes = [c for c in index.get("changes", []) if isinstance(c, dict)]
    stamped = [(t, c) for c in changes if (t := _entry_time(c)) is not None]
    mark = max((t for t, _ in stamped), default=None)
    floor = _parse_time(since)
    fresh = sorted(
        ((t, c) for t, c in stamped if floor is not None and t > floor and c.get("type") != "internal"),
        key=lambda pair: pair[0],
        reverse=True,
    )
    catalog = {e["id"]: e for e in index.get("catalog", []) if isinstance(e, dict) and "id" in e}
    return {
        "available": True,
        "mark": mark.strftime("%Y-%m-%dT%H:%M:%SZ") if mark else "",
        "total": len(fresh),
        "more": max(0, len(fresh) - MAX_ENTRIES),
        "entries": [_shape(c, catalog) for _, c in fresh[:MAX_ENTRIES]],
    }
