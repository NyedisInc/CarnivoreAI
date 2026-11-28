
from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.plugins.save.offload import constants as C
from src.plugins.sdk.blob_codec import Throttle

logger = structlog.get_logger()


class BatchBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class StepResult:

    ok: bool
    code: str = ""
    detail: str = ""
    conversations: int = 0
    bytes: int = 0
    stuck: Tuple[str, ...] = ()


@dataclass
class Item:

    session_uuid: str
    status: str
    code: str = ""
    detail: str = ""
    conversations: int = 0
    bytes: int = 0


@dataclass
class Batch:

    id: str
    max_sessions: int
    idle_days: int
    planned: int
    state: str
    started_at: float
    finished_at: Optional[float] = None
    items: List[Item] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i.status == status)

    @property
    def bytes(self) -> int:
        return sum(i.bytes for i in self.items if i.status == C.ITEM_OFFLOADED)


def classify(result: StepResult) -> str:
    if result.ok:
        return C.ITEM_OFFLOADED
    if result.stuck or result.code not in C.BATCH_SKIP_CODES:
        return C.ITEM_FAILED
    return C.ITEM_SKIPPED


class BatchRunner:

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._batches: Dict[str, Batch] = {}
        self._latest: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pace: Optional[Throttle] = None

    def start(self, planned: Sequence[str], offload_one: Callable[[str], StepResult], *, max_sessions: int, idle_days: int, pace: Throttle,
              on_change: Callable[[], None] = lambda: None) -> Batch:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise BatchBusy("a batch is already running")
            batch = Batch(uuid.uuid4().hex[:12], max_sessions, idle_days, len(planned), C.BATCH_RUNNING if planned else C.BATCH_DONE, self._clock(),
                          None if planned else self._clock())
            self._batches[batch.id] = batch
            self._latest = batch.id
            self._stop.clear()
            self._pace = pace
            if planned:
                self._thread = threading.Thread(target=self._run, args=(batch, list(planned), offload_one, pace, on_change), name="save-offload-batch", daemon=True)
                self._thread.start()
            return copy.deepcopy(batch)

    def _run(self, batch: Batch, planned: List[str], offload_one: Callable[[str], StepResult], pace: Throttle, on_change: Callable[[], None]) -> None:
        state = C.BATCH_DONE
        try:
            for session_uuid in planned:
                if self._stop.is_set() or pace.cancelled:
                    state = C.BATCH_STOPPED
                    break
                started = time.monotonic()
                item = self._step(session_uuid, offload_one)
                with self._lock:
                    batch.items.append(item)
                on_change()
                if item.status == C.ITEM_FAILED:
                    state = C.BATCH_FAILED
                    break
                pace.rest(time.monotonic() - started)
        except Exception as exc:  # noqa: BLE001
            logger.error("offload_batch_crashed", batch=batch.id, error_type=type(exc).__name__, error=str(exc)[:300])
            state = C.BATCH_FAILED
            with self._lock:
                batch.items.append(Item("", C.ITEM_FAILED, "batch_crashed", f"{type(exc).__name__}: {str(exc)[:200]}"))
        with self._lock:
            batch.state, batch.finished_at = state, self._clock()
        on_change()
        logger.info("offload_batch_ended", batch=batch.id, state=state, offloaded=batch.count(C.ITEM_OFFLOADED), skipped=batch.count(C.ITEM_SKIPPED), failed=batch.count(C.ITEM_FAILED))

    @staticmethod
    def _step(session_uuid: str, offload_one: Callable[[str], StepResult]) -> Item:
        result = offload_one(session_uuid)
        status = classify(result)
        if status != C.ITEM_OFFLOADED:
            logger.warning("offload_batch_session_not_offloaded", session_uuid=session_uuid, status=status, code=result.code, stuck=len(result.stuck))
        detail = result.detail[:300] + (f" (stuck: {result.stuck[0]})" if result.stuck else "")
        return Item(session_uuid, status, result.code, detail, result.conversations, result.bytes)

    def get(self, batch_id: str) -> Optional[Batch]:
        with self._lock:
            found = self._batches.get(batch_id)
            return copy.deepcopy(found) if found is not None else None

    def latest(self) -> Optional[Batch]:
        with self._lock:
            return copy.deepcopy(self._batches[self._latest]) if self._latest else None

    def stop(self, batch_id: str) -> Optional[Batch]:
        with self._lock:
            found = self._batches.get(batch_id)
            if found is None:
                return None
            if found.state == C.BATCH_RUNNING:
                self._stop.set()
            return copy.deepcopy(found)

    def stop_running(self) -> bool:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            pace = self._pace
            if running:
                self._stop.set()
        if running and pace is not None:
            pace.cancel()
        return running

    def join(self, timeout: Optional[float] = None) -> bool:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()
