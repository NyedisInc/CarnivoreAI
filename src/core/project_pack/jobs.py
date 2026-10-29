
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import structlog

from src.core import resource_push
from src.core.project_pack import constants as K
from src.core.resource_push import topics as resource_topics

logger = structlog.get_logger()


class JobBusy(Exception):
    pass


@dataclass
class Progress:

    project_id: int
    phase: str = "starting"
    done: int = 0
    total: int = 0
    _last_notice: float = field(default=0.0, repr=False)

    def set_phase(self, phase: str, total: int = 0) -> None:
        self.phase, self.done, self.total = phase, 0, total
        self._notify(force=True)

    def add(self, nbytes: int) -> None:
        self.done += nbytes
        self._notify()

    def _notify(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_notice >= K.PROGRESS_NOTIFY_SECONDS:
            self._last_notice = now
            resource_push.notify(resource_topics.PROJECTS)

    def as_dict(self) -> Dict[str, Any]:
        pct = int(100 * self.done / self.total) if self.total else None
        return {"phase": self.phase, "done_bytes": self.done, "total_bytes": self.total, "percent": pct}


_LOCK = threading.Lock()
_CURRENT: Dict[int, Progress] = {}
_THREADS: Dict[int, threading.Thread] = {}


def progress_of(project_id: int) -> Optional[Dict[str, Any]]:
    p = _CURRENT.get(project_id)
    return p.as_dict() if p else None


def any_running() -> bool:
    return bool(_CURRENT)


def start(project_id: int, work: Callable[[Progress], None]) -> Progress:
    with _LOCK:
        if _CURRENT:
            raise JobBusy("another pack or unpack job is running; ask for a new plan when it has finished")
        progress = Progress(project_id)
        _CURRENT[project_id] = progress

    def runner() -> None:
        try:
            work(progress)
        except Exception:  # noqa: BLE001
            logger.exception("project_pack_job_crashed", project_id=project_id)
        finally:
            with _LOCK:
                _CURRENT.pop(project_id, None)
            resource_push.notify(resource_topics.PROJECTS)

    thread = threading.Thread(target=runner, name=f"project-pack-{project_id}", daemon=True)
    _THREADS[project_id] = thread
    thread.start()
    return progress


def join(project_id: int, timeout: float = 60.0) -> None:
    thread = _THREADS.get(project_id)
    if thread:
        thread.join(timeout)
