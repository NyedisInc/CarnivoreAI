
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from src.cplugs.save import pipeline_seed
from src.cplugs.sdk import pipeline_rows

ROW_ID: str = "backups"
CONTRIBUTOR: str = "save"


@dataclass
class _Last:

    failed: bool = False
    error: Optional[str] = None


class BackupsRecord:

    def __init__(self, wall: Callable[[], float] = time.time, notify: Callable[[], None] = pipeline_rows.changed) -> None:
        self._wall = wall
        self._notify = notify
        self._lock = threading.Lock()
        self._passes = 0
        self._captures = 0
        self._written = 0
        self._finished_at: Optional[float] = None
        self._duration_ms = 0.0
        self._last_pass = _Last()
        self._last_capture = _Last()
        self._seed: Optional[pipeline_seed.TreeFacts] = None

    def seed(self, facts: pipeline_seed.TreeFacts) -> bool:
        with self._lock:
            if facts.newest_at is None or self._finished_at is not None and self._seed is None:
                return False
            self._seed = facts
            self._finished_at = facts.newest_at
        self._notify()
        return True

    def _finish(self, duration_s: float) -> None:
        self._finished_at = self._wall()
        self._seed = None
        self._duration_ms = round(max(0.0, duration_s) * 1000.0, 1)

    def record_pass(self, *, written: int, failed: int, duration_s: float, error: Optional[str] = None) -> None:
        with self._lock:
            self._passes += 1
            self._written = max(0, int(written))
            self._last_pass = _Last(failed=bool(failed) or error is not None, error=error or ("capture_failed" if failed else None))
            self._finish(duration_s)
        self._notify()

    def record_capture(self, *, failed: bool, duration_s: float) -> None:
        with self._lock:
            self._captures += 1
            self._last_capture = _Last(failed=failed, error="capture_failed" if failed else None)
            self._finish(duration_s)
        self._notify()

    def rows(self) -> List[pipeline_rows.PipelineRow]:
        with self._lock:
            if self._finished_at is None:
                return []
            if self._seed is not None:
                facts = self._seed
                return [pipeline_rows.PipelineRow(
                    plugin=ROW_ID, finished_at=self._finished_at, duration_ms=None, runs=None, seeded=True,
                    detail={"conversations": facts.conversations, "size_bytes": facts.size_bytes})]
            bad = next((last for last in (self._last_pass, self._last_capture) if last.failed), None)
            return [pipeline_rows.PipelineRow(
                plugin=ROW_ID, finished_at=self._finished_at, duration_ms=self._duration_ms,
                runs=self._passes + self._captures, events=self._written,
                outcome=pipeline_rows.OUTCOME_FAILED if bad else pipeline_rows.OUTCOME_OK, error=bad.error if bad else None)]


RECORD = BackupsRecord()


def seed_from_disk(vault_root: Path) -> bool:
    return RECORD.seed(pipeline_seed.scan_vault(vault_root))


def register() -> None:
    pipeline_rows.register(CONTRIBUTOR, RECORD.rows)


def unregister() -> None:
    pipeline_rows.unregister(CONTRIBUTOR)
