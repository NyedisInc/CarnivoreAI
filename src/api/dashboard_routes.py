
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.api.preferences_routes import _store, broadcast_changed
from src.core import ui_preferences, ui_preferences_store
from src.core.board_transfer.document import fresh_board_id

logger = structlog.get_logger()
router = APIRouter(tags=["dashboards"])

FIRST_DASHBOARD_ID = "home"
"""The board every earlier single Home layout became; the fallback active one."""


class _Write(BaseModel):
    """Fields every write body may carry."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: Optional[int] = None


class CreateRequest(_Write):

    name: str = Field(min_length=1, max_length=ui_preferences.MAX_HOME_BOARD_NAME)
    layout: Optional[Dict[str, Any]] = None
    copy_of: Optional[str] = None


class RenameRequest(_Write):

    name: str = Field(min_length=1, max_length=ui_preferences.MAX_HOME_BOARD_NAME)


class LayoutRequest(_Write):

    layout: Dict[str, Any]


class ActivateRequest(_Write):
    pass


def _refuse(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail, **extra})


def effective_active(home: Dict[str, Any]) -> Optional[str]:
    ids = [board.get("id") for board in home.get("boards", []) if isinstance(board, dict)]
    active = home.get("active")
    if active in ids:
        return active
    if FIRST_DASHBOARD_ID in ids:
        return FIRST_DASHBOARD_ID
    return ids[0] if ids else None


def _answer(home: Optional[Dict[str, Any]], revision: int) -> Dict[str, Any]:
    if not isinstance(home, dict):
        return {"dashboards": [], "active": None, "revision": revision, "synced": False}
    listed = [{"id": board["id"], "name": board["name"]} for board in home.get("boards", [])]
    return {"dashboards": listed, "active": effective_active(home), "revision": revision, "synced": True}


def _read_home(request: Request) -> Dict[str, Any]:
    home = _store(request).read()["values"].get("home_layout")
    if not isinstance(home, dict):
        raise _refuse(409, "home_not_synced", "open home in a browser once before changing dashboards")
    return home


def _find(home: Dict[str, Any], dashboard_id: str) -> Dict[str, Any]:
    for board in home.get("boards", []):
        if board.get("id") == dashboard_id:
            return board
    raise _refuse(404, "dashboard_unknown", f"there is no dashboard {dashboard_id}")


async def _commit(request: Request, home: Dict[str, Any], expected: Optional[int], event: str, **context: Any) -> Dict[str, Any]:
    result = _store(request).update({"home_layout": home}, expected_revision=expected)
    if result.status == ui_preferences_store.REJECTED_INVALID:
        raise _refuse(400, "dashboard_refused", result.detail or "refused")
    if result.status == ui_preferences_store.STALE_REVISION:
        raise _refuse(409, "preferences_stale", "the dashboards changed since you read them", revision=result.revision)
    if result.status == ui_preferences_store.COMMITTED:
        await broadcast_changed(request, result, None)
    logger.info(event, **context)
    return _answer(home, result.revision)


@router.get("/dashboards", dependencies=[Depends(require_auth)])
async def list_dashboards(request: Request) -> Dict[str, Any]:
    """Every dashboard, the active one, and the preference revision."""
    block = _store(request).read()
    return _answer(block["values"].get("home_layout"), block["revision"])


@router.post("/dashboards", dependencies=[Depends(require_auth)])
async def create_dashboard(body: CreateRequest, request: Request) -> Dict[str, Any]:
    """Add a dashboard; it does not become active."""
    home = _read_home(request)
    boards: List[Dict[str, Any]] = list(home.get("boards", []))
    if len(boards) >= ui_preferences.MAX_HOME_BOARDS:
        raise _refuse(400, "dashboards_full", f"at most {ui_preferences.MAX_HOME_BOARDS} dashboards; remove one first")
    if body.layout is not None:
        layout = body.layout
    else:
        source = body.copy_of or effective_active(home) or ""
        layout = _find(home, source)["layout"]
    new_id = fresh_board_id([board.get("id") for board in boards])
    name = " ".join(body.name.split())
    if not name:
        raise _refuse(400, "dashboard_refused", "a dashboard needs a name")
    home = {**home, "boards": [*boards, {"id": new_id, "name": name, "layout": layout}]}
    answer = await _commit(request, home, body.expected_revision, "dashboard_created", dashboard=new_id)
    return {**answer, "created": new_id}


@router.patch("/dashboards/{dashboard_id}", dependencies=[Depends(require_auth)])
async def rename_dashboard(dashboard_id: str, body: RenameRequest, request: Request) -> Dict[str, Any]:
    """Rename a dashboard."""
    home = _read_home(request)
    _find(home, dashboard_id)
    name = " ".join(body.name.split())
    if not name:
        raise _refuse(400, "dashboard_refused", "a dashboard needs a name")
    boards = [{**board, "name": name} if board.get("id") == dashboard_id else board for board in home["boards"]]
    return await _commit(request, {**home, "boards": boards}, body.expected_revision, "dashboard_renamed", dashboard=dashboard_id)


@router.put("/dashboards/{dashboard_id}/layout", dependencies=[Depends(require_auth)])
async def set_dashboard_layout(dashboard_id: str, body: LayoutRequest, request: Request) -> Dict[str, Any]:
    """Replace one dashboard's grid, leaving every other dashboard as stored (the pop-out's save)."""
    home = _read_home(request)
    _find(home, dashboard_id)
    boards = [{**board, "layout": body.layout} if board.get("id") == dashboard_id else board for board in home["boards"]]
    return await _commit(request, {**home, "boards": boards}, body.expected_revision, "dashboard_layout_saved", dashboard=dashboard_id)


@router.post("/dashboards/{dashboard_id}/activate", dependencies=[Depends(require_auth)])
async def activate_dashboard(dashboard_id: str, request: Request, body: Optional[ActivateRequest] = None) -> Dict[str, Any]:
    """Make a dashboard the home screen on every browser."""
    home = _read_home(request)
    _find(home, dashboard_id)
    expected = body.expected_revision if body else None
    return await _commit(request, {**home, "active": dashboard_id}, expected, "dashboard_activated", dashboard=dashboard_id)


@router.delete("/dashboards/{dashboard_id}", dependencies=[Depends(require_auth)])
async def delete_dashboard(dashboard_id: str, request: Request, expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Remove a dashboard; the active one (and so the last one) is refused."""
    home = _read_home(request)
    _find(home, dashboard_id)
    if dashboard_id == effective_active(home):
        raise _refuse(409, "dashboard_active", "this dashboard is the home screen; make another one active first")
    boards = [board for board in home["boards"] if board.get("id") != dashboard_id]
    return await _commit(request, {**home, "boards": boards}, expected_revision, "dashboard_deleted", dashboard=dashboard_id)
