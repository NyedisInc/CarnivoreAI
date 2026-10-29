
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.backup_health import constants as K

logger = structlog.get_logger()

OK, FIRING, UNKNOWN, BUSY = "ok", "firing", "unknown", "busy"
_TM_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{6})")
_HOUR, _DAY = 3600.0, 86400.0

TmutilRunner = Callable[[], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Verdict:

    key: str
    state: str
    severity: str = "warn"
    title_key: str = ""
    detail_key: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)


def _hours(seconds: float) -> int:
    return int(seconds // _HOUR)


def _env_file_volume() -> Optional[str]:
    from dotenv import dotenv_values

    from src.api.enrollment_routes import env_file_path
    from src.core.product_identity import env_names

    path = env_file_path()
    try:
        values = dotenv_values(path, interpolate=False)
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("backup_health_env_file_unreadable", path=str(path), error_type=type(exc).__name__)
        return None
    lowered = {str(key).lower(): value for key, value in values.items()}
    for name in env_names(K.BACKUP_VOLUME_ENV):
        if name.lower() in lowered:
            return lowered[name.lower()] or ""
    return None


def backup_volume() -> Optional[Path]:
    from src.core.product_identity import env_value

    found = env_value(K.BACKUP_VOLUME_ENV)
    raw = (found if found is not None else _env_file_volume() or "").strip()
    return None if not raw or raw.lower() == K.BACKUP_VOLUME_OFF else Path(raw)


def check_usb_backup(now: float, volume: Optional[Path] = None, max_age_days: float = K.BACKUP_MAX_AGE_DAYS) -> Optional[Verdict]:
    root = volume if volume is not None else backup_volume()
    if root is None:
        return None
    key = K.KEY_USB
    if not root.is_dir() or not os.path.ismount(root):
        return Verdict(key, FIRING, "warn", K.TITLE_USB_MISSING, K.DETAIL_USB_MISSING, {"path": str(root)})
    try:
        stamps = [p.stat().st_mtime for p in root.glob(K.BACKUP_DIR_GLOB) if p.is_dir()]
    except OSError as exc:
        logger.warning("backup_health_usb_unreadable", error_type=type(exc).__name__)
        return Verdict(key, UNKNOWN)
    age = (now - max(stamps)) if stamps else None
    if age is None or age > max_age_days * _DAY:
        days = None if age is None else int(age // _DAY)
        return Verdict(key, FIRING, "warn", K.TITLE_USB_STALE, K.DETAIL_USB_STALE,
                       {"days": days if days is not None else "no", "max_days": int(max_age_days), "path": str(root)})
    return Verdict(key, OK)


def _run_tmutil() -> "subprocess.CompletedProcess[str]":
    return subprocess.run([K.TMUTIL_BIN, "latestbackup"], capture_output=True, text=True, timeout=K.TMUTIL_TIMEOUT_S, check=False)


def _run_tmutil_destinations() -> "subprocess.CompletedProcess[str]":
    return subprocess.run([K.TMUTIL_BIN, "destinationinfo"], capture_output=True, text=True, timeout=K.TMUTIL_TIMEOUT_S, check=False)


def _run_tmutil_status() -> "subprocess.CompletedProcess[str]":
    return subprocess.run([K.TMUTIL_BIN, "status"], capture_output=True, text=True, timeout=K.TMUTIL_TIMEOUT_S, check=False)


def backup_running(status: Optional[TmutilRunner]) -> bool:
    if status is None:
        return False
    try:
        done = status()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("backup_health_tmutil_status_failed", error_type=type(exc).__name__)
        return False
    return re.search(K.TM_RUNNING_PATTERN, getattr(done, "stdout", "") or "") is not None


def _says(done: Any, markers: Tuple[str, ...]) -> bool:
    text = f"{getattr(done, 'stdout', '') or ''}\n{getattr(done, 'stderr', '') or ''}".lower()
    return any(marker in text for marker in markers)


def time_machine_reason(done: Any, destinations: Optional[TmutilRunner]) -> str:
    """Why ``tmutil latestbackup`` could not be read: ``access``, ``no_destination`` or ``unreadable``.

    ``latestbackup`` itself says so when Full Disk Access is missing. Otherwise ``destinationinfo`` (no access needed)
    tells a Mac with no backup destination from one whose destination exists but could not be read.
    Inputs: done (the latestbackup result); destinations (a runner for destinationinfo, or None to skip that look).
    Output: one of K.TM_REASON_*. Example: time_machine_reason(done_with_fda_error, None) -> 'access'
    """
    if _says(done, K.TM_ACCESS_MARKERS):
        return K.TM_REASON_ACCESS
    if _says(done, K.TM_NO_DESTINATION_MARKERS):
        return K.TM_REASON_NO_DESTINATION
    if destinations is not None:
        try:
            info = destinations()
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("backup_health_tmutil_destinations_failed", error_type=type(exc).__name__)
            return K.TM_REASON_UNREADABLE
        if _says(info, K.TM_NO_DESTINATION_MARKERS):
            return K.TM_REASON_NO_DESTINATION
    return K.TM_REASON_UNREADABLE


def _tm_unknown(key: str, reason: str) -> Verdict:
    return Verdict(key, UNKNOWN, "warn", K.TITLE_TM_UNKNOWN, K.DETAIL_TM_UNKNOWN_BY_REASON[reason], {"reason": reason})


def check_time_machine(now: float, runner: Optional[TmutilRunner] = None,
                       max_age_hours: float = K.TIME_MACHINE_MAX_AGE_HOURS,
                       destinations: Optional[TmutilRunner] = None, status: Optional[TmutilRunner] = None) -> Verdict:
    key = K.KEY_TIME_MACHINE
    busy_look = status if status is not None else (_run_tmutil_status if runner is None else None)
    try:
        done = (runner or _run_tmutil)()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("backup_health_tmutil_failed", error_type=type(exc).__name__)
        if backup_running(busy_look):
            return Verdict(key, BUSY)
        return _tm_unknown(key, K.TM_REASON_UNREADABLE)
    found = _TM_STAMP.search(done.stdout or "") if done.returncode == 0 else None
    if found is None:
        look = destinations if destinations is not None else (_run_tmutil_destinations if runner is None else None)
        reason = time_machine_reason(done, look)
        if reason == K.TM_REASON_UNREADABLE and backup_running(busy_look):
            return Verdict(key, BUSY)
        said = (getattr(done, "stderr", "") or getattr(done, "stdout", "") or "").strip().splitlines()[:1]
        logger.warning("backup_health_tmutil_unreadable", returncode=done.returncode, reason=reason, tmutil_said=said)
        return _tm_unknown(key, reason)
    taken = datetime.strptime(found.group(1), "%Y-%m-%d-%H%M%S").timestamp()
    age = now - taken
    if age > max_age_hours * _HOUR:
        return Verdict(key, FIRING, "warn", K.TITLE_TM_STALE, K.DETAIL_TM_STALE,
                       {"hours": _hours(age), "max_hours": int(max_age_hours)})
    return Verdict(key, OK)
