
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_CLEANUP_DAYS = 30
SECONDS_PER_DAY = 86400
SETTINGS_LAYERS: Tuple[Tuple[str, str], ...] = (
    ("user", "~/.claude/settings.json"), ("local", "~/.claude/settings.local.json"),
    ("managed", "/Library/Application Support/ClaudeCode/managed-settings.json"),
    ("managed", "/etc/claude-code/managed-settings.json"))


def read_cleanup_setting(layers: Tuple[Tuple[str, str], ...]) -> Tuple[Optional[Any], Optional[str]]:
    value: Optional[Any] = None
    source: Optional[str] = None
    for name, path in layers:
        try:
            with open(os.path.expanduser(path)) as fh:
                found = json.load(fh).get("cleanupPeriodDays")
        except (OSError, ValueError, AttributeError):
            continue
        if found is not None:
            value, source = found, name
    return value, source


def cleanup_evidence(mtimes: List[float], settings: Optional[str]) -> Dict[str, Any]:
    now = time.time()
    ages = sorted((now - m) / SECONDS_PER_DAY for m in mtimes)
    layers = (("explicit", settings),) if settings else SETTINGS_LAYERS
    configured, source = read_cleanup_setting(layers)
    return {"configured_cleanupPeriodDays": configured, "configured_from_layer": source,
            "layers_checked": [p for _n, p in layers],
            "default_when_absent_days": DEFAULT_CLEANUP_DAYS,
            "oldest_file_age_days": round(ages[-1], 1) if ages else None,
            "files_older_than_default": sum(1 for a in ages if a > DEFAULT_CLEANUP_DAYS),
            "files_total": len(ages)}
