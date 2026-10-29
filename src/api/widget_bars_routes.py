
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.preferences_routes import _store, broadcast_changed
from src.core import ui_preferences_store
from src.core.widget_placement.widget_bars import WIDGET_BAR_FIELDS

logger = structlog.get_logger()

router = APIRouter(tags=["preferences"])


@router.post("/preferences/widget-bars/reset", dependencies=[Depends(require_auth)])
async def reset_widget_bars(request: Request) -> Dict[str, Any]:
    """Clear the bars' chrome and both bars' contents in ONE write, one revision bump, one broadcast.

    Output: ``{"status": "committed" | "unchanged", "revision", "values"}``; ``unchanged`` with no bump when all
      three fields were already absent. The broadcast carries no origin client id, so every browser, the caller
      included, applies it.
    Raises: HTTPException 500 when config.json is missing, 503 when the store is not mounted.
    """
    store = _store(request)
    try:
        result = store.update({field: None for field in WIDGET_BAR_FIELDS})
    except FileNotFoundError as exc:
        logger.error("widget_bars_reset_config_missing", error=str(exc))
        raise HTTPException(status_code=500, detail="Configuration not found. Run setup_auth.py first.")
    if result.status == ui_preferences_store.COMMITTED:
        await broadcast_changed(request, result, None)
    return result.as_payload()
