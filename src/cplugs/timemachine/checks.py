
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import structlog

from src.cplugs.timemachine import constants as K

logger = structlog.get_logger()

OK, FIRING, UNKNOWN, BUSY = "ok", "firing", "unknown", "busy"
_TM_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{6})")
_HOUR = 3600.0


@dataclass(frozen=True)
class Verdict:

    state: str
    params: Dict[str, Any] = field(default_factory=dict)


def tmutil(verb: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([K.TMUTIL_BIN, verb], capture_output=True, text=True, timeout=K.TMUTIL_TIMEOUT_S, check=False)


def backup_running() -> bool:
    try:
        done = tmutil("status")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("timemachine_tmutil_status_failed", error_type=type(exc).__name__)
        return False
    return re.search(K.TM_RUNNING_PATTERN, getattr(done, "stdout", "") or "") is not None


def _says(done: Any, markers: Tuple[str, ...]) -> bool:
    text = f"{getattr(done, 'stdout', '') or ''}\n{getattr(done, 'stderr', '') or ''}".lower()
    return any(marker in text for marker in markers)


def time_machine_reason(done: Any) -> str:
    if _says(done, K.TM_ACCESS_MARKERS):
        return K.TM_REASON_ACCESS
    if _says(done, K.TM_NO_DESTINATION_MARKERS):
        return K.TM_REASON_NO_DESTINATION
    try:
        info = tmutil("destinationinfo")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("timemachine_tmutil_destinations_failed", error_type=type(exc).__name__)
        return K.TM_REASON_UNREADABLE
    return K.TM_REASON_NO_DESTINATION if _says(info, K.TM_NO_DESTINATION_MARKERS) else K.TM_REASON_UNREADABLE


def check_time_machine(now: float, max_age_hours: float = K.TIME_MACHINE_MAX_AGE_HOURS) -> Optional[Verdict]:
    try:
        done = tmutil("latestbackup")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("timemachine_tmutil_failed", error_type=type(exc).__name__)
        return Verdict(BUSY) if backup_running() else Verdict(UNKNOWN, {"reason": K.TM_REASON_UNREADABLE})
    found = _TM_STAMP.search(done.stdout or "") if done.returncode == 0 else None
    if found is None:
        reason = time_machine_reason(done)
        if reason == K.TM_REASON_NO_DESTINATION:
            return None
        if reason == K.TM_REASON_UNREADABLE and backup_running():
            return Verdict(BUSY)
        said = (getattr(done, "stderr", "") or getattr(done, "stdout", "") or "").strip().splitlines()[:1]
        logger.warning("timemachine_tmutil_unreadable", returncode=done.returncode, reason=reason, tmutil_said=said)
        return Verdict(UNKNOWN, {"reason": reason})
    age = now - datetime.strptime(found.group(1), "%Y-%m-%d-%H%M%S").timestamp()
    if age > max_age_hours * _HOUR:
        return Verdict(FIRING, {"hours": int(age // _HOUR), "max_hours": int(max_age_hours)})
    return Verdict(OK)
