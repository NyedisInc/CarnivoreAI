from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core.app_alerts import constants as alert_const

logger = structlog.get_logger()

GONE = "gone"


def record(kind: str, alert_key: str, at: Optional[float] = None) -> Dict[str, Any]:
    return {"channel": "alert", "kind": kind, "alert_key": alert_key, "at": time.time() if at is None else float(at)}


def alerts_db_path() -> Path:
    from src.config import settings as app_settings  # noqa: PLC0415
    from src.core.db import db_path_for  # noqa: PLC0415

    return db_path_for(app_settings.get_state_dir())


def _epoch(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def state_of(alert_key: str) -> Tuple[str, Optional[float]]:
    from src.core.db import connect  # noqa: PLC0415

    try:
        with closing(connect(alerts_db_path(), create=False)) as conn:
            row = conn.execute(
                f"SELECT state, dismissed_at, resolved_at, snoozed_until FROM {alert_const.TABLE} WHERE dedupe_key = ? "
                "ORDER BY id DESC LIMIT 1", (alert_key,)).fetchone()
    except (sqlite3.Error, OSError) as exc:
        logger.warning("automation_delivered_state_unreadable", alert_key=alert_key, error=str(exc))
        return GONE, None
    if row is None:
        return GONE, None
    state, dismissed_at, resolved_at, snoozed_until = row
    at = {"dismissed": dismissed_at, "resolved": resolved_at, "snoozed": snoozed_until}.get(state)
    return state, _epoch(at)


def with_state(run: Dict[str, Any]) -> Dict[str, Any]:
    delivered = run.get("delivered")
    if not delivered:
        return run
    state, state_at = state_of(delivered["alert_key"])
    return {**run, "delivered": {**delivered, "state": state, "state_at": state_at}}
