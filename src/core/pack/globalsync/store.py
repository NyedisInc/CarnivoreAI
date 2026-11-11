
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.json_artifact import atomic_write_json

DEFAULTS: Dict[str, bool] = {"enabled": False, "auto": False, "claude": True, "codex": True}


def clean_settings(raw: Any) -> Dict[str, bool]:
    base = raw if isinstance(raw, dict) else {}
    return {k: base[k] if isinstance(base.get(k), bool) else d for k, d in DEFAULTS.items()}


class Status:

    def __init__(self, path: Path, clock=time.time) -> None:
        self.path, self._clock = Path(path), clock

    def all(self) -> Dict[str, Dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        rows = raw.get("computers") if isinstance(raw, dict) else None
        return {k: v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}

    def get(self, install_id: str) -> Optional[Dict[str, Any]]:
        return self.all().get(install_id)

    def record(self, install_id: str, state: str, **fields: Any) -> None:
        rows = self.all()
        old = rows.get(install_id) or {}
        row = {"state": state, "at": self._clock(), **fields}
        if "digest" not in row and old.get("digest"):
            row["digest"] = old["digest"]
        rows[install_id] = row
        atomic_write_json(self.path, {"v": 1, "computers": rows}, log_event="pack_global_status_write_failed")

    def forget(self, install_id: str) -> None:
        rows = self.all()
        if rows.pop(install_id, None) is not None:
            atomic_write_json(self.path, {"v": 1, "computers": rows}, log_event="pack_global_status_write_failed")
