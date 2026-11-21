
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from src.plugins.sdk import session_bring_up


def untagged_wake_target(list_key: str, lead_key: str, asleep: Iterable[Dict[str, Any]]) -> Optional[str]:
    if not list_key.isdigit():
        return None
    sleepers = list(asleep)
    if lead_key and any(s["session_uuid"] == lead_key for s in sleepers):
        return lead_key
    return session_bring_up.pick_sleeper(sleepers, int(list_key), lead_key)
