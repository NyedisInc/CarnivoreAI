
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.core.backup_health import offloaded_marker


def attach(state_dir: Path, groups: List[Dict[str, Any]]) -> None:
    rows = offloaded_marker.read(state_dir).rows
    for group in groups:
        found = rows.get(group["conversation_id"])
        group["offloaded"] = found is not None
        group["offloaded_at"] = (found.offloaded_at or None) if found is not None else None
