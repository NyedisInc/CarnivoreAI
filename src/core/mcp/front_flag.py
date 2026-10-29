
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import HTTPException

from src.models.ui_show import ShowRequest

logger = structlog.get_logger()

FRONT_PROPERTY: Dict[str, Any] = {
    "type": "boolean", "default": False,
    "description": "OPTIONAL, off by default. true also brings the row into view in the window you used last (the same as "
                   "sidebar_show); other windows are left alone. With no window used yet the open still succeeds and front says why.",
}


async def bring_front(request: Any, kind: str, item_id: str) -> Dict[str, Any]:
    from src.api import ui_show_routes

    try:
        answer = await ui_show_routes.show_item(ShowRequest(kind=kind, id=item_id), request)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        reason = str(detail.get("code", "refused")).removeprefix("ui_show_")
        logger.info("front_flag_not_shown", kind=kind, reason=reason)
        return {"shown": False, "reason": reason, "detail": detail.get("detail", "")}
    return {"shown": True, "seq": answer.seq}
