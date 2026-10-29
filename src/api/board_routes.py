
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

from src.api.auth import require_auth
from src.api.preferences_routes import _store, broadcast_changed
from src.core import item_settings_store, resource_push, session_change_notice, ui_preferences, ui_preferences_store
from src.core.resource_push import topics as resource_topics
from src.models.websocket import WSMessageType
from src.core.board_transfer import MAX_BOARD_FILE_BYTES, BoardFileError, apply_widget_settings, build_export, plan_import
from src.core.board_transfer.document import fresh_board_id
from src.core.db import DatastoreUnreadableError, connect, db_path_for

logger = structlog.get_logger()
router = APIRouter(tags=["boards"])


class ImportRequest(BaseModel):
    """The import body. ``document`` is the parsed file, checked by ``plan_import``."""

    model_config = ConfigDict(extra="forbid")

    document: Dict[str, Any]
    dry_run: StrictBool = False
    apply_drawer_zone: StrictBool = False
    expected_revision: Optional[int] = None
    client_id: Optional[str] = None


def _refuse(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail, **extra})


def _widget_settings() -> Dict[str, Any]:
    from src.config import settings

    path = db_path_for(settings.get_state_dir())
    if not path.exists():
        return {}
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            return dict(item_settings_store.read_document(conn)["items"].get("widget", {}))
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        logger.warning("board_export_settings_unreadable", error=str(exc))
        return {}


def _apply_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    from src.config import settings as app_settings

    path = db_path_for(app_settings.get_state_dir())
    try:
        if not path.exists():
            raise DatastoreUnreadableError("the settings datastore has not been created yet")
        with closing(connect(path, create=False)) as conn:
            applied, refused = apply_widget_settings(conn, settings)
            return {"applied": applied, "refused": refused, "revision": item_settings_store.document_revision(conn)}
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        logger.warning("board_import_settings_unavailable", error=str(exc))
        return {"applied": [], "refused": [f"{name}: the settings store is unavailable, its settings were skipped" for name in sorted(settings)], "revision": None}


@router.get("/boards/{board_id}/export", dependencies=[Depends(require_auth)])
async def export_board(board_id: str, request: Request) -> JSONResponse:
    """One stored Home board as a board file (a download)."""
    values = _store(request).read()["values"]
    settings = await run_in_threadpool(_widget_settings)
    try:
        document = build_export(values, board_id, settings)
    except BoardFileError as exc:
        raise _refuse(404, "board_unknown", str(exc))
    logger.info("board_exported", board=board_id, widgets=len(document["settings"]))
    filename = f"{board_id}.carnivore-board.json"
    return JSONResponse(document, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/boards/import", dependencies=[Depends(require_auth)])
async def import_board(body: ImportRequest, request: Request) -> Dict[str, Any]:
    """Preview or add an imported board (module docstring)."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > 2 * MAX_BOARD_FILE_BYTES:
        raise _refuse(400, "board_file_invalid", f"a board file is at most {MAX_BOARD_FILE_BYTES // 1024} KiB")
    try:
        plan = plan_import(body.document)
    except BoardFileError as exc:
        raise _refuse(400, "board_file_invalid", str(exc))
    store = _store(request)
    block = store.read()
    home = block["values"].get("home_layout")
    boards = list(home.get("boards", [])) if isinstance(home, dict) else []
    if len(boards) >= ui_preferences.MAX_HOME_BOARDS:
        plan.refusals.append(f"home already has {ui_preferences.MAX_HOME_BOARDS} boards, the most it keeps; remove one first")
    if plan.refusals:
        logger.info("board_import_refused", count=len(plan.refusals))
        raise _refuse(400, "board_refused", plan.refusals[0], refusals=plan.refusals, preview=plan.preview())
    if body.dry_run:
        return {"status": "preview", "preview": plan.preview()}
    if not isinstance(home, dict):
        raise _refuse(409, "home_not_synced", "open home in a browser once before importing a board")
    board_id = fresh_board_id([board.get("id") for board in boards])
    changes: Dict[str, Any] = {"home_layout": {**home, "boards": [*boards, {"id": board_id, "name": plan.name, "layout": plan.layout}]}}
    if body.apply_drawer_zone and plan.drawer_zone is not None:
        changes["drawer_zone"] = plan.drawer_zone
    result = store.update(changes, expected_revision=body.expected_revision)
    if result.status == ui_preferences_store.REJECTED_INVALID:
        raise _refuse(400, "board_refused", result.detail or "refused", refusals=[result.detail or "refused"])
    if result.status == ui_preferences_store.STALE_REVISION:
        raise _refuse(409, "preferences_stale", "the boards changed since you read them", revision=result.revision)
    if result.status == ui_preferences_store.COMMITTED:
        await broadcast_changed(request, result, body.client_id)
    logger.info("board_imported", board=board_id, widgets=len(plan.widgets))
    outcome = await run_in_threadpool(_apply_settings, plan.settings) if plan.settings else {"applied": [], "refused": [], "revision": None}
    if outcome["applied"]:
        session_change_notice.publish(
            request.app.state, {"type": WSMessageType.ITEM_SETTINGS_CHANGED, "revision": outcome["revision"]}
        )
        resource_push.notify(resource_topics.ITEM_SETTINGS)
    return {
        "status": "imported",
        "board_id": board_id,
        "revision": result.revision,
        "preview": plan.preview(),
        "settings_applied": outcome["applied"],
        "settings_refused": outcome["refused"],
    }
