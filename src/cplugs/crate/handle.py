
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional


class ExportCancelled(Exception):
    pass


class JobHandle:

    def __init__(self, job_id: str, *, on_change: Optional[Callable[["JobHandle"], None]] = None,
                 pacer: Any = None) -> None:
        self.job_id = job_id
        self._on_change = on_change
        self._pacer = pacer
        self._stop = threading.Event()
        self.phase_name = ""
        self.phases: List[str] = []
        self.done_bytes = self.total_bytes = self.files_done = self.files_total = 0
        self.temp_paths: List[str] = []
        self.publish: Optional[Dict[str, Any]] = None

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change(self)

    def phase(self, name: str, total: int = 0, files: int = 0) -> None:
        self.phase_name = name
        self.phases.append(name)
        self.total_bytes, self.done_bytes, self.files_total, self.files_done = total, 0, files, 0
        self._changed()

    def add(self, nbytes: int, files: int = 0) -> None:
        self.done_bytes += nbytes
        self.files_done += files
        self._changed()

    def temp(self, path: str) -> None:
        if path not in self.temp_paths:
            self.temp_paths.append(path)
        self._changed()

    def untemp(self, path: str) -> None:
        if path in self.temp_paths:
            self.temp_paths.remove(path)
        self._changed()

    def published(self, record: Dict[str, Any]) -> None:
        self.publish = dict(record)
        self._changed()

    def cancel(self) -> None:
        self._stop.set()

    def cancelled(self) -> bool:
        return self._stop.is_set()

    def check(self) -> None:
        if self._stop.is_set():
            raise ExportCancelled(self.job_id)

    def rest(self, worked_seconds: float) -> None:
        if self._pacer is not None:
            self._pacer.rest(worked_seconds)
