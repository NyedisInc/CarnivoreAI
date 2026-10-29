
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.crate_format.constants import HOME_CLAUDE
from src.core.crate_import import files_place

SETTINGS_FILE = "settings.json"
KEY = "cleanupPeriodDays"
DEFAULT_DAYS = 30
KEEP_DAYS = 36500
NS_PER_DAY = 86_400 * 10**9
REFUSED_UNREADABLE = "settings_unreadable"


def settings_path(home: Path) -> Path:
    return Path(home) / SETTINGS_FILE


def read_settings(home: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    path = settings_path(home)
    if not os.path.lexists(path):
        return {}, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}, REFUSED_UNREADABLE
    return (data, None) if isinstance(data, dict) else ({}, REFUSED_UNREADABLE)


def period_days(settings: Dict[str, Any]) -> int:
    value = settings.get(KEY)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else DEFAULT_DAYS


def plan(placements: List[files_place.Placement], writing: frozenset, home: Path, *, now_ns: Optional[int] = None) -> Dict[str, Any]:
    now = now_ns if now_ns is not None else time.time_ns()
    settings, refused = read_settings(home)
    days = period_days(settings)
    ages = [(now - p.record.mtime_ns) // NS_PER_DAY for p in placements
            if p.action == files_place.ACT_PLACE and p.dest is not None and p.cls in (files_place.CLASS_ABSENT, files_place.CLASS_GROW)
            and p.record.conversation_id in writing and p.record.role in files_place.CONVERSATION_ROLES and p.record.home == HOME_CLAUDE and p.record.mtime_ns]
    older = [a for a in ages if a >= days]
    return {"period_days": days, "files_older": len(older), "oldest_days": max(ages) if ages else 0,
            "needs_guard": bool(older) and days < KEEP_DAYS, "keep_days": KEEP_DAYS, "refused": refused}
