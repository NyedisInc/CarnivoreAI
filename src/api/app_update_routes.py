
from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.api.auth import require_auth
from src.core.app_update import store

logger = structlog.get_logger()
router = APIRouter(prefix="/app-update", tags=["app-update"], dependencies=[Depends(require_auth)])


class AutoUpdateSetting(BaseModel):

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool


class UpdaterReport(BaseModel):
    """The packaged app's updater state, as ``macOS/auto-update.js`` reports it.

    Example: {"state": "available", "current_version": "1.16.2", "latest_version": "1.16.3"}
    """

    model_config = ConfigDict(extra="forbid")

    state: str
    current_version: str = Field(default="", max_length=64)
    latest_version: str = Field(default="", max_length=64)
    percent: Optional[int] = Field(default=None, ge=0, le=100)
    detail: Optional[str] = Field(default=None, max_length=500)
    checked_at: Optional[float] = None


def _require_attached() -> None:
    if not store.status()["attached"]:
        raise HTTPException(status_code=409, detail="no desktop app is attached to this server")


@router.get("")
async def get_status() -> dict:
    """Return the updater status. Example: GET /api/v1/app-update -> {"attached": true, "state": "current", ...}"""
    return store.status()


@router.put("/auto-update")
async def set_auto_update(body: AutoUpdateSetting) -> dict:
    """Turn automatic updates on or off (config.json ``updates.auto_update``) and return the status.

    Example: PUT {"enabled": true} -> {"auto_update": true, ...}
    """
    try:
        await asyncio.to_thread(store.write_auto_update, body.enabled)
    except (OSError, ValueError) as exc:
        logger.warning("app_update_toggle_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="the setting could not be saved") from exc
    return store.status()


@router.post("/check")
async def check_now() -> dict:
    """Ask the app to check the feed now. Output: the status with the queued command_seq."""
    _require_attached()
    store.request("check")
    return store.status()


@router.post("/install")
async def install_now() -> dict:
    """Ask the app to download (if needed) and restart into the update. 409 when there is no update to install."""
    _require_attached()
    if store.status()["state"] not in store.INSTALLABLE:
        raise HTTPException(status_code=409, detail="there is no update to install")
    store.request("install")
    return store.status()


@router.post("/state")
async def report_state(body: UpdaterReport) -> dict:
    """The packaged app reports its updater state. Output: the status. 422 on an unknown state."""
    try:
        store.record_report(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return store.status()
