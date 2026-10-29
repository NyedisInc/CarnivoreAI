
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.version import repo_root

logger = structlog.get_logger()

router = APIRouter(tags=["features"])


def _index_path() -> Path:
    return repo_root() / "features" / "index.json"


@router.get("/feature-catalog", dependencies=[Depends(require_auth)])
async def get_feature_catalog() -> dict[str, Any]:
    """Return the generated feature catalog, or an honest empty state.

    Description: reads ``features/index.json`` verbatim. When the file is
      absent, unreadable, or not valid JSON, logs the reason and answers
      the same empty shape rather than raising - this endpoint backs a UI
      panel, and a malformed or missing catalog file must never turn into
      a 500 there.
    Inputs: none.
    Output: dict - ``{"available": bool, "areas": [...], "catalog": [...],
      "changes": [...]}``. ``changes`` entries carry a ``release`` field
      (``"Unreleased"`` or a ``vX.Y.Z`` tag) when the file was generated
      after issue #844.
    Example: GET /api/v1/feature-catalog
    """
    path = _index_path()
    empty: dict[str, Any] = {"available": False, "areas": [], "catalog": [], "changes": []}
    if not path.is_file():
        logger.info("features_index_missing", path=str(path))
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("features_index_unreadable", path=str(path), error=str(exc))
        return empty
    if not isinstance(data, dict):
        logger.warning("features_index_malformed", path=str(path))
        return empty
    return {
        "available": True,
        "areas": data.get("areas", []),
        "catalog": data.get("catalog", []),
        "changes": data.get("changes", []),
    }
