
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import structlog

from src.core.json_artifact import atomic_write_json, read_json_object

log = structlog.get_logger(__name__)

FILE_NAME = "notification_sms_day_count.json"


class SmsDayCount:

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self._path = Path(state_dir) / FILE_NAME if state_dir is not None else None
        self._rows: Optional[Dict[str, Dict[str, object]]] = None

    def _load(self) -> Dict[str, Dict[str, object]]:
        if self._rows is None:
            raw = read_json_object(self._path, log_event="notify_sms_count_unreadable") if self._path else None
            rows: Dict[str, Dict[str, object]] = {}
            for dest_id, row in (raw or {}).items():
                if isinstance(row, dict) and isinstance(row.get("day"), str) and isinstance(row.get("count"), int):
                    rows[str(dest_id)] = {"day": row["day"], "count": max(row["count"], 0)}
            self._rows = rows
        return self._rows

    def used(self, dest_id: str, day: str) -> int:
        row = self._load().get(dest_id)
        return int(row["count"]) if row and row["day"] == day else 0

    def add(self, dest_id: str, day: str, count: int) -> None:
        rows = self._load()
        rows[dest_id] = {"day": day, "count": self.used(dest_id, day) + count}
        if self._path is not None:
            atomic_write_json(self._path, rows, log_event="notify_sms_count_write_failed")
