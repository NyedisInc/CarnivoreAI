
from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping

import structlog

from src.core.app_alerts import service
from src.core.notifications import contracts, types
from src.core.notifications.sources import common

logger = structlog.get_logger(__name__)

NOTICE_TYPE = "automation_notice"

_SEVERITY = {"error": contracts.SEVERITY_ERROR, "warn": contracts.SEVERITY_WARN, "warning": contracts.SEVERITY_WARN}


def event_for(row: Mapping[str, Any]) -> contracts.NotifyEvent:
    type_id = types.type_for_alert_key(row["key"])
    text = (row.get("params") or {}).get("text") if type_id == NOTICE_TYPE else None
    return contracts.NotifyEvent(
        type_id=type_id, kind="alert", title=common.type_title(type_id), ts=common.now(),
        severity=_SEVERITY.get(str(row.get("severity")), contracts.SEVERITY_INFO),
        instance_key=f"alert:{row['id']}", details=str(text) if text else None,
    )


def make_listener(loop: asyncio.AbstractEventLoop) -> Callable[[Mapping[str, Any]], None]:
    def listener(row: Mapping[str, Any]) -> None:
        event = event_for(row)
        try:
            loop.call_soon_threadsafe(contracts.emit, event)
        except RuntimeError:
            logger.warning("alert_notify_loop_closed", type_id=event.type_id)

    return listener


def install(loop: asyncio.AbstractEventLoop) -> None:
    service.on_raised(make_listener(loop))
