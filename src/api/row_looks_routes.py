
from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.core import row_looks
from src.core.browser_pages import open_pages
from src.core.open_files import open_list
from src.models.row_looks import RowLookInfo, RowLookList, RowLookRequest, RowLookResponse

logger = structlog.get_logger()

router = APIRouter(tags=["row-looks"], dependencies=[Depends(require_auth)])
_ID = re.compile(r"^[0-9a-f]{16}$")


async def _row_is_open(row_id: str, request: Request) -> bool:
    if not _ID.match(row_id):
        return False
    if open_list.get(row_id) is not None or open_pages.get(row_id) is not None:
        return True
    from src.api import browser_routes  # noqa: PLC0415

    manager = getattr(request.app.state, "browser_manager", None)
    if manager is None:
        return False
    try:
        await browser_routes._row_or_404(manager, row_id)
    except HTTPException:
        return False
    return True


@router.get("/sidebar/row-looks", response_model=RowLookList)
async def list_row_looks() -> RowLookList:
    """Every styled row's look, by row id. Output: RowLookList."""
    return RowLookList(looks={k: RowLookInfo(color=v.color, icon=v.icon) for k, v in row_looks.listing().items()})


@router.put("/sidebar/row-looks/{row_id}", response_model=RowLookResponse)
async def set_row_look(row_id: str, body: RowLookRequest, request: Request) -> RowLookResponse:
    """Restyle one opened row. Output: RowLookResponse. Errors: 404 row_look_row_not_found; 422 unknown name."""
    if not await _row_is_open(row_id, request):
        raise HTTPException(status_code=404, detail={"code": "row_look_row_not_found", "detail": "no open file, page or browser has that id"})
    look = row_looks.set_look(row_id, {k: getattr(body, k) for k in body.model_fields_set & {"color", "icon"}})
    logger.info("row_look_set", row_id=row_id, color=look.color, icon=look.icon)
    return RowLookResponse(row_id=row_id, color=look.color, icon=look.icon)
