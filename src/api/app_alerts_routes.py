
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
import structlog
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.config import settings as app_settings
from src.core.app_alerts import constants as K
from src.core.app_alerts import kinds, recheck, service

logger = structlog.get_logger()

OPEN_TIMEOUT_S = 10.0

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_auth)])


def _db_path() -> Path:
    from src.core.db import db_path_for

    return db_path_for(app_settings.get_state_dir())


def _state_dir() -> Path:
    """This install's state directory. Separate function so tests can point it at a temp dir."""
    return app_settings.get_state_dir()


class WidgetReportBody(BaseModel):
    """One widget problem report: which widget, where, at what size in grid units, and why."""

    widget: str = Field(pattern=r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$", max_length=80)
    zone: Literal["home", "terminal", "drawer", "popout"]
    w: int = Field(ge=0, le=256)
    h: int = Field(ge=0, le=256)
    reason: Literal["untested", "too-small", "too-large", "shape", "reported"]


class SnoozeBody(BaseModel):
    """How long to snooze, in minutes (1 to one week)."""

    minutes: int = Field(ge=1, le=K.MAX_SNOOZE_MINUTES)


class SystemSettingsBody(BaseModel):
    """Which macOS settings pane to open: a name from ``kinds.SYSTEM_PANES``, never a URL."""

    pane: Literal["full_disk_access"]


@router.get("")
async def list_alerts(state: Literal["active", "all"] = "active",
                      limit: int = Query(K.DEFAULT_LIST_LIMIT, ge=1, le=K.MAX_LIST_LIMIT)) -> Dict[str, Any]:
    """The alert list and the badge counts. Output: {alerts, counts}."""
    path = _db_path()
    return await asyncio.to_thread(service.list_view, path, include_closed=state == "all", limit=limit)


@router.post("/dismiss-resolved")
async def dismiss_resolved() -> Dict[str, int]:
    """Dismiss every resolved alert. Output: {dismissed: n}."""
    path = _db_path()
    return {"dismissed": await asyncio.to_thread(service.dismiss_resolved, path)}


@router.post("/widget-report")
async def widget_report(body: WidgetReportBody) -> Dict[str, Any]:
    """Raise one warn alert for a widget problem, deduped per widget, zone and size.

    Output: the alert row. 503 when the alert store could not take it (raise_alert logs why).
    Example: POST /alerts/widget-report {"widget": "core.notes", "zone": "home", "w": 2, "h": 1,
             "reason": "too-small"} -> key app_alert.widget.core.notes.home.2x1
    """
    path = _db_path()
    key = f"{K.KEY_PREFIX}widget.{body.widget}.{body.zone}.{body.w}x{body.h}"
    row = await asyncio.to_thread(
        service.raise_alert, key, source="widgets", severity=K.SEV_WARN,
        title_key=f"{K.KEY_PREFIX}widget.report.title",
        params={"widget": body.widget, "zone": body.zone, "w": body.w, "h": body.h, "reason": body.reason},
        detail_key=f"{K.KEY_PREFIX}widget.report.detail.{body.reason.replace('-', '_')}",
        auto_resolve=False, db_path=path,
    )
    if row is None:
        raise HTTPException(status_code=503, detail="the alert store could not take the report")
    return row


@router.post("/{alert_id}/dismiss")
async def dismiss(alert_id: int) -> Dict[str, Any]:
    """Dismiss one alert. Output: the alert. 404 when absent."""
    path = _db_path()
    row = await asyncio.to_thread(service.dismiss, path, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such alert")
    return row


@router.post("/{alert_id}/snooze")
async def snooze(alert_id: int, body: SnoozeBody) -> Dict[str, Any]:
    """Snooze one open alert. Output: the alert. 404 absent, 409 not open."""
    path = _db_path()
    row = await asyncio.to_thread(service.snooze, path, alert_id, body.minutes)
    if row is not None:
        return row
    exists = await asyncio.to_thread(service.exists, path, alert_id)
    raise HTTPException(status_code=409 if exists else 404, detail="alert is not open" if exists else "no such alert")


@router.post("/{alert_id}/recheck")
async def recheck_alert(alert_id: int) -> Dict[str, Any]:
    """Run the alert's producer check now. Output: the alert as it stands (state ``resolved`` once the fault cleared).

    404 when absent, 409 when this kind of alert has no re-check. Example: POST /alerts/7/recheck -> {"state": "resolved", ...}
    """
    path = _db_path()
    row = await asyncio.to_thread(service.get, path, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such alert")
    if not recheck.supports(row["key"]):
        raise HTTPException(status_code=409, detail="this alert has no re-check")
    await asyncio.to_thread(recheck.run, _state_dir(), path, row)
    return await asyncio.to_thread(service.get, path, alert_id) or row


@router.post("/open-system-settings")
async def open_system_settings(body: SystemSettingsBody) -> Dict[str, Any]:
    """
    The pane is looked up in ``kinds.SYSTEM_PANES``; the caller never supplies a URL. 501 off macOS, 502 when ``open`` fails.
    Example: POST /alerts/open-system-settings {"pane": "full_disk_access"}
    """
    if sys.platform != "darwin":
        raise HTTPException(status_code=501, detail="system settings can only be opened on macOS")
    url = kinds.SYSTEM_PANES[body.pane]
    try:
        done = await asyncio.to_thread(subprocess.run, ["open", url], capture_output=True, text=True,
                                       timeout=OPEN_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("alert_open_settings_failed", pane=body.pane, error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="could not open system settings") from exc
    if done.returncode != 0:
        logger.warning("alert_open_settings_refused", pane=body.pane, returncode=done.returncode)
        raise HTTPException(status_code=502, detail="could not open system settings")
    return {"opened": True, "pane": body.pane}
