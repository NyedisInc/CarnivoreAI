
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from src.api.auth import require_auth
from src.config.auto_sleep import MAX_IDLE_MINUTES, MIN_IDLE_MINUTES, AutoSleepConfig
from src.core import resource_push, session_change_notice
from src.core.resource_push import topics as resource_topics
from src.core.auto_sleep import store
from src.models.auto_sleep import AutoSleepState, AutoSleepWrite, KeepAwakeWrite, SleepHoldEntry
from src.models.websocket import WSMessageType
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(tags=["auto-sleep"])


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def _db_path() -> Path:
    from src.config import settings
    from src.core.db import db_path_for

    return db_path_for(settings.get_state_dir())


def _names_for(uuids: List[str]) -> List[str]:
    from src.core.db import DatastoreUnreadableError, connect

    path = _db_path()
    if not uuids or not path.exists():
        return []
    marks = ",".join("?" for _ in uuids)
    try:
        with closing(connect(path, create=False)) as conn:
            rows = conn.execute(
                f"SELECT session_uuid, tmux_name FROM sessions WHERE session_uuid IN ({marks}) "
                "AND archived_at IS NULL AND tmux_name IS NOT NULL",
                tuple(uuids),
            ).fetchall()
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        logger.warning("auto_sleep_names_unread", error=type(exc).__name__)
        return []
    by_uuid: Dict[str, str] = {str(r["session_uuid"]): str(r["tmux_name"]) for r in rows}
    return [by_uuid[u] for u in uuids if u in by_uuid]


def _mac_awake(request: Request) -> bool:
    guard = getattr(request.app.state, "mac_awake_guard", None)
    return bool(guard.active) if guard is not None else False


def _holding(request: Request) -> List[SleepHoldEntry]:
    sleeper = getattr(request.app.state, "auto_sleeper", None)
    held = list(sleeper.holds.values()) if sleeper is not None else []
    return [SleepHoldEntry(session=name, reasons=list(hold.reasons), text=hold.text)
            for name, hold in held]


def _state(
    config: AutoSleepConfig, *, mac_awake: bool, holding: List[SleepHoldEntry] | None = None,
) -> AutoSleepState:
    return AutoSleepState(
        holding=holding or [],
        enabled=config.enabled,
        idle_minutes=config.idle_minutes,
        unread_blocks_sleep=config.unread_blocks_sleep,
        unread_idle_minutes=config.unread_idle_minutes,
        min_idle_minutes=MIN_IDLE_MINUTES,
        max_idle_minutes=MAX_IDLE_MINUTES,
        keep_awake=_names_for(config.keep_awake),
        keep_awake_session_uuids=list(config.keep_awake),
        mac_awake=mac_awake,
    )


def reconcile_mac_awake(request: Request, config: AutoSleepConfig) -> None:
    guard = getattr(request.app.state, "mac_awake_guard", None)
    if guard is not None:
        guard.reconcile(config.mac_awake_demand())


def _unreadable(exc: Exception) -> HTTPException:
    return api_error(500, "config_unreadable", None, error_type=type(exc).__name__)


def _resolve_uuid(tmux_name: str) -> str:
    from src.core.db import DatastoreUnreadableError, connect
    from src.core.session_group_errors import SessionGroupError
    from src.core.session_group_membership import session_uuid_for_name

    path = _db_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="no session carries that name")
    try:
        with closing(connect(path, create=False)) as conn:
            return session_uuid_for_name(conn, tmux_name)
    except SessionGroupError as exc:
        raise api_error(404, "not_found", exc, step="_resolve_uuid") from exc
    except (DatastoreUnreadableError, OSError, sqlite3.Error) as exc:
        raise api_error(503, "datastore_unavailable", exc, step="resolve_uuid") from exc


def _changed(request: Request) -> None:
    session_change_notice.publish(request.app.state, {"type": WSMessageType.AUTO_SLEEP_CHANGED})
    resource_push.notify(resource_topics.AUTO_SLEEP)


@router.get("/auto-sleep", response_model=AutoSleepState, dependencies=[Depends(require_auth)])
async def get_auto_sleep(request: Request) -> AutoSleepState:
    """The auto-sleep toggle, its idle minutes, who is kept awake, and
    whether this server currently holds a macOS idle-sleep assertion for it.

    Raises: HTTPException(500) - config.json is missing or not readable JSON.
    """
    try:
        config = await asyncio.to_thread(store.read, _config_path())
    except (FileNotFoundError, ValueError) as exc:
        raise _unreadable(exc) from exc
    return await asyncio.to_thread(_state, config, mac_awake=_mac_awake(request), holding=_holding(request))


@router.put("/auto-sleep", response_model=AutoSleepState, dependencies=[Depends(require_auth)])
async def put_auto_sleep(body: AutoSleepWrite, request: Request) -> AutoSleepState:
    """Turn auto-sleep on or off and/or set its idle minutes and unread policy.

    Raises: HTTPException(422) - minutes outside the accepted range;
      HTTPException(500) - config.json is missing, unreadable, or holds an
      auto_sleep block the store refuses to overwrite.
    """
    for field, minutes in (
        ("idle_minutes", body.idle_minutes),
        ("unread_idle_minutes", body.unread_idle_minutes),
    ):
        if minutes is not None and not MIN_IDLE_MINUTES <= minutes <= MAX_IDLE_MINUTES:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": f"invalid_{field}",
                    "detail": f"{field} must be {MIN_IDLE_MINUTES} to {MAX_IDLE_MINUTES}",
                },
            )
    try:
        _status, config = await asyncio.to_thread(
            store.set_settings,
            _config_path(),
            enabled=body.enabled,
            idle_minutes=body.idle_minutes,
            unread_blocks_sleep=body.unread_blocks_sleep,
            unread_idle_minutes=body.unread_idle_minutes,
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("auto_sleep_unwritable", error=type(exc).__name__)
        raise _unreadable(exc) from exc
    _changed(request)
    return await asyncio.to_thread(_state, config, mac_awake=_mac_awake(request), holding=_holding(request))


@router.put(
    "/auto-sleep/keep-awake", response_model=AutoSleepState, dependencies=[Depends(require_auth)]
)
async def put_keep_awake(body: KeepAwakeWrite, request: Request) -> AutoSleepState:
    """Turn one session's keep-awake flag on or off.

    Description: name the session by ``session_uuid`` or by ``tmux_name``,
      exactly one. A name is resolved to the durable uuid (the live row
      carrying it, else the newest), and the uuid is what is stored, so the
      flag follows the session across a restart, a sleep and its wake.
    Raises: HTTPException(422) - neither or both names given, or a
      malformed uuid; 404 - no row carries the name; 503 - datastore
      unreadable; 500 - config.json unusable.
    """
    if (body.session_uuid is None) == (body.tmux_name is None):
        raise HTTPException(
            status_code=422,
            detail={"code": "name_one_session", "detail": "give session_uuid or tmux_name, not both"},
        )
    uuid = body.session_uuid
    if uuid is None:
        uuid = await asyncio.to_thread(_resolve_uuid, str(body.tmux_name))
    try:
        _status, config = await asyncio.to_thread(
            store.set_keep_awake, _config_path(), uuid, body.keep_awake
        )
    except (FileNotFoundError, store.StoredBlockInvalid) as exc:
        raise _unreadable(exc) from exc
    except ValueError as exc:
        if "Invalid JSON" in str(exc) or "Invalid config shape" in str(exc):
            raise _unreadable(exc) from exc
        raise api_error(422, "invalid_keep_awake", exc) from exc
    _changed(request)
    await asyncio.to_thread(reconcile_mac_awake, request, config)
    return await asyncio.to_thread(_state, config, mac_awake=_mac_awake(request), holding=_holding(request))


class MacAwakeAlways(BaseModel):
    """Body and answer of ``/system/keep-awake``. Example: {"always": true}"""

    model_config = ConfigDict(extra="forbid")

    always: StrictBool


@router.get("/system/keep-awake", response_model=MacAwakeAlways, dependencies=[Depends(require_auth)])
async def get_system_keep_awake() -> MacAwakeAlways:
    """Whether the Mac is held awake regardless of sessions (the tray's Keep Mac Awake).

    Output: {"always": bool}. Raises: HTTPException(500) - config.json unusable.
    Example: GET /api/v1/system/keep-awake -> {"always": false}
    """
    try:
        config = await asyncio.to_thread(store.read, _config_path())
    except (FileNotFoundError, ValueError) as exc:
        raise _unreadable(exc) from exc
    return MacAwakeAlways(always=config.mac_awake_always)


@router.put("/system/keep-awake", response_model=MacAwakeAlways, dependencies=[Depends(require_auth)])
async def put_system_keep_awake(body: MacAwakeAlways, request: Request) -> MacAwakeAlways:
    """Hold the Mac awake regardless of sessions, or stop doing so; persisted, so it survives a restart.

    Description: stored as ``auto_sleep.mac_awake_always`` through the one config writer, then the
      #617 caffeinate guard is reconciled (same ``caffeinate -i -w <server pid>`` child, boot
      reconcile included). The flag never changes any session's own auto-sleep.
    Raises: HTTPException(500) - config.json missing or its block invalid.
    Example: PUT /api/v1/system/keep-awake {"always": true} -> {"always": true}
    """
    try:
        _status, config = await asyncio.to_thread(store.set_mac_awake_always, _config_path(), body.always)
    except (FileNotFoundError, ValueError) as exc:
        raise _unreadable(exc) from exc
    _changed(request)
    await asyncio.to_thread(reconcile_mac_awake, request, config)
    return MacAwakeAlways(always=config.mac_awake_always)
