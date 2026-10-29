
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def untagged_wake_target(list_key: str, lead_key: str, asleep: Iterable[Dict[str, Any]]) -> Optional[str]:
    if not list_key.isdigit():
        return None
    sleepers = list(asleep)
    if lead_key and any(s["session_uuid"] == lead_key for s in sleepers):
        return lead_key
    return next((s["session_uuid"] for s in sleepers if str(s.get("project_id")) == list_key), None)
