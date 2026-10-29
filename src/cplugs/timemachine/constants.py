
from __future__ import annotations

from typing import Tuple

TIME_MACHINE_MAX_AGE_HOURS: float = 24.0
TMUTIL_BIN: str = "tmutil"
TMUTIL_TIMEOUT_S: float = 15.0
TM_RUNNING_PATTERN: str = r"\bRunning\s*=\s*1\b"
TM_UNKNOWN_PASSES_TO_ALERT: int = 2
TM_REASON_ACCESS: str = "access"
TM_REASON_NO_DESTINATION: str = "no_destination"
TM_REASON_UNREADABLE: str = "unreadable"
TM_ACCESS_MARKERS: Tuple[str, ...] = ("full disk access", "operation not permitted", "permission denied", "not authorized")
TM_NO_DESTINATION_MARKERS: Tuple[str, ...] = ("no destinations", "not configured")

PERIOD_S: float = 900.0
FIRST_PASS_DELAY_S: float = 60.0

ALERT_KEY: str = "time_machine"
TITLE_STALE: str = "cplug.timemachine.alert.stale.title"
DETAIL_STALE: str = "cplug.timemachine.alert.stale.detail"
TITLE_UNKNOWN: str = "cplug.timemachine.alert.unknown.title"
DETAIL_UNKNOWN_BY_REASON: dict = {
    TM_REASON_ACCESS: "cplug.timemachine.alert.unknown.detail.access",
    TM_REASON_UNREADABLE: "cplug.timemachine.alert.unknown.detail.unreadable",
}
EXPLAIN_BY_REASON: dict = {
    TM_REASON_ACCESS: "cplug.timemachine.alert.unknown.explain.access",
    TM_REASON_UNREADABLE: "cplug.timemachine.alert.unknown.explain.unreadable",
}
ACTION_CHECK_ACCESS: str = "cplug.timemachine.action.check_access"
