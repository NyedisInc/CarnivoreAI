
from __future__ import annotations

from typing import Tuple

TABLE: str = "app_alerts"

SEV_INFO: str = "info"
SEV_WARN: str = "warn"
SEV_ERROR: str = "error"
SEVERITIES: Tuple[str, ...] = (SEV_INFO, SEV_WARN, SEV_ERROR)

STATE_ACTIVE: str = "active"
STATE_RESOLVED: str = "resolved"
STATE_DISMISSED: str = "dismissed"
STATE_SNOOZED: str = "snoozed"
STATES: Tuple[str, ...] = (STATE_ACTIVE, STATE_RESOLVED, STATE_DISMISSED, STATE_SNOOZED)
OPEN_STATES: Tuple[str, ...] = (STATE_ACTIVE, STATE_SNOOZED)

RETENTION_DAYS: int = 30
MAX_SNOOZE_MINUTES: int = 7 * 24 * 60
DEFAULT_LIST_LIMIT: int = 200
MAX_LIST_LIMIT: int = 500

KEY_PREFIX: str = "app_alert."

PROBE_BUDGET_SECONDS: float = 2.0

FRAME_RAISED: str = "app_alert.raised"
FRAME_UPDATED: str = "app_alert.updated"
FRAME_RESOLVED: str = "app_alert.resolved"

