
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import structlog

from src.core.app_alerts import constants as K
from src.core.app_alerts import kinds
from src.core.app_alerts import store
from src.core.app_alerts.store import AlertInputError, AlertSpec

logger = structlog.get_logger(__name__)

Publisher = Callable[[Dict[str, Any]], None]

_lock = threading.Lock()
_db_path: Optional[Path] = None
_publisher: Optional[Publisher] = None

_raised_listeners: List[Callable[[Mapping[str, Any]], None]] = []

_FRAME_FOR = {store.EV_RAISED: K.FRAME_RAISED, store.EV_UPDATED: K.FRAME_UPDATED, store.EV_RESOLVED: K.FRAME_RESOLVED}


def on_raised(listener: Callable[[Mapping[str, Any]], None]) -> None:
    _raised_listeners.append(listener)


def configure(db_path: Optional[Path], publisher: Optional[Publisher]) -> None:
    global _db_path, _publisher
    with _lock:
        _db_path, _publisher = db_path, publisher
        if db_path is None and publisher is None:
            _raised_listeners.clear()


def build_frame(row: Mapping[str, Any], event: str) -> Dict[str, Any]:
    return {"type": _FRAME_FOR[event], "id": row["id"], "key": row["key"], "severity": row["severity"],
            "state": row["state"], "count": row["count"], "notify_type": row["notify_type"]}


def _publish(row: Optional[Mapping[str, Any]], event: str) -> None:
    publisher = _publisher
    if publisher is None or row is None or event not in _FRAME_FOR:
        return
    try:
        publisher(build_frame(row, event))
    except RuntimeError as exc:
        logger.warning("app_alert_publish_failed", key=row["key"], error=str(exc))


def _connect(db_path: Path) -> sqlite3.Connection:
    from src.core.db import connect

    return connect(db_path, create=False)


def raise_alert(key: str, *, source: str, severity: str, title_key: str,
                params: Optional[Mapping[str, Any]] = None, detail_key: Optional[str] = None,
                sticky: bool = False, auto_resolve: bool = True,
                actions: Sequence[Mapping[str, Any]] = (), db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = db_path or _db_path
    if path is None:
        logger.debug("app_alert_unconfigured", key=key)
        return None
    spec = AlertSpec(key=key, source=source, severity=severity, title_key=title_key, params=dict(params or {}),
                     detail_key=detail_key, sticky=sticky, auto_resolve=auto_resolve, actions=tuple(actions))
    try:
        with closing(_connect(path)) as conn:
            row, event = store.raise_alert(conn, spec)
    except (sqlite3.Error, OSError, AlertInputError) as exc:
        logger.error("app_alert_raise_failed", key=key, source=source, error=str(exc), error_type=type(exc).__name__)
        return None
    if event == store.EV_RAISED:
        logger.info("app_alert_raised", key=key, source=source, severity=severity, alert_id=row["id"])
        for listener in _raised_listeners:
            try:
                listener(row)
            except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
                logger.warning("app_alert_listener_failed", key=key, error_type=type(exc).__name__)
    _publish(row, event)
    return row


def resolve(key: str, *, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = db_path or _db_path
    if path is None:
        return []
    try:
        with closing(_connect(path)) as conn:
            rows = store.resolve(conn, key)
    except (sqlite3.Error, OSError) as exc:
        logger.error("app_alert_resolve_failed", key=key, error=str(exc), error_type=type(exc).__name__)
        return []
    for row in rows:
        logger.info("app_alert_resolved", key=key, alert_id=row["id"])
        _publish(row, store.EV_RESOLVED)
    return rows


def list_view(db_path: Path, *, include_closed: bool, limit: int) -> Dict[str, Any]:
    with closing(_connect(db_path)) as conn:
        for row in store.wake_snoozed(conn):
            _publish(row, store.EV_UPDATED)
        store.prune(conn)
        return {"alerts": store.list_alerts(conn, include_closed=include_closed, limit=limit),
                "counts": store.counts(conn), "sources": kinds.source_catalog()}


def dismiss(db_path: Path, alert_id: int) -> Optional[Dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        row = store.dismiss(conn, alert_id)
    _publish(row, store.EV_UPDATED)
    return row


def snooze(db_path: Path, alert_id: int, minutes: int) -> Optional[Dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        row = store.snooze(conn, alert_id, minutes)
    _publish(row, store.EV_UPDATED)
    return row


def dismiss_resolved(db_path: Path) -> int:
    with closing(_connect(db_path)) as conn:
        return store.dismiss_resolved(conn)


def exists(db_path: Path, alert_id: int) -> bool:
    with closing(_connect(db_path)) as conn:
        return store.get(conn, alert_id) is not None


def get(db_path: Path, alert_id: int) -> Optional[Dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        return store.get(conn, alert_id)
