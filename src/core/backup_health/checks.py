
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.backup_health import constants as K

logger = structlog.get_logger()

OK, FIRING, UNKNOWN = "ok", "firing", "unknown"
_DAY = 86400.0


@dataclass(frozen=True)
class Verdict:

    key: str
    state: str
    severity: str = "warn"
    title_key: str = ""
    detail_key: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)


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
