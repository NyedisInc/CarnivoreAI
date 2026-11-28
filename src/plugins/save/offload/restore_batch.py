
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

KIND_SESSION = "session"
KIND_CONVERSATION = "conversation"


class RestoreBatchBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:

    kind: str
    id: str


@dataclass(frozen=True)
class RestoreStep:

    ok: bool
    code: str = ""
    detail: str = ""
    conversations: int = 0
    bytes: int = 0


@dataclass
class RestoreItem:

    kind: str
    id: str
    status: str
    code: str = ""
    detail: str = ""
    conversations: int = 0
    bytes: int = 0


@dataclass
class RestoreBatch:

    id: str
    planned: int
    state: str
    started_at: float
    finished_at: Optional[float] = None
    items: List[RestoreItem] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i.status == status)

    @property
    def bytes(self) -> int:
        return sum(i.bytes for i in self.items if i.status == C.ITEM_RESTORED)

    def failed_ids(self) -> List[str]:
        return [i.id for i in self.items if i.status == C.ITEM_RESTORE_FAILED and i.id]

    def restored_ids(self) -> List[str]:
        return [i.id for i in self.items if i.status == C.ITEM_RESTORED]


class RestoreBatchRunner:

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._batches: Dict[str, RestoreBatch] = {}
        self._latest: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, targets: Sequence[Target], restore_one: Callable[[Target], RestoreStep], *, pace: Throttle, on_change: Callable[[], None] = lambda: None,
              on_end: Callable[[RestoreBatch], None] = lambda batch: None) -> RestoreBatch:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RestoreBatchBusy("a restore batch is already running")
            batch = RestoreBatch(uuid.uuid4().hex[:12], len(targets), C.BATCH_RUNNING if targets else C.BATCH_DONE, self._clock(), None if targets else self._clock())
            self._batches[batch.id] = batch
            self._latest = batch.id
            self._stop.clear()
            if targets:
                self._thread = threading.Thread(target=self._run, args=(batch, list(targets), restore_one, pace, on_change, on_end), name="save-offload-restore-batch", daemon=True)
                self._thread.start()
            return copy.deepcopy(batch)

    def _run(self, batch: RestoreBatch, targets: List[Target], restore_one: Callable[[Target], RestoreStep], pace: Throttle, on_change: Callable[[], None],
             on_end: Callable[[RestoreBatch], None]) -> None:
        state = C.BATCH_DONE
        try:
            for target in targets:
                if self._stop.is_set() or pace.cancelled:
                    state = C.BATCH_STOPPED
                    break
                started = time.monotonic()
                item = self._step(target, restore_one)
                with self._lock:
                    batch.items.append(item)
                on_change()
                if item.status == C.ITEM_RESTORE_FAILED and item.code in C.RESTORE_STOP_CODES:
                    state = C.BATCH_STOPPED
                    break
                pace.rest(time.monotonic() - started)
        except Exception as exc:  # noqa: BLE001
            logger.error("offload_restore_batch_crashed", batch=batch.id, error_type=type(exc).__name__, error=str(exc)[:300])
            state = C.BATCH_STOPPED
            with self._lock:
                batch.items.append(RestoreItem("", "", C.ITEM_RESTORE_FAILED, "batch_crashed", f"{type(exc).__name__}: {str(exc)[:200]}"))
        with self._lock:
            batch.state, batch.finished_at = state, self._clock()
            ended = copy.deepcopy(batch)
        self._announce(ended, on_end, on_change)

    @staticmethod
    def _announce(ended: RestoreBatch, on_end: Callable[[RestoreBatch], None], on_change: Callable[[], None]) -> None:
        try:
            on_end(ended)
        except (OSError, ValueError) as exc:
            logger.error("offload_restore_batch_alert_failed", batch=ended.id, error_type=type(exc).__name__, error=str(exc)[:300])
        on_change()
        logger.info("offload_restore_batch_ended", batch=ended.id, state=ended.state, restored=ended.count(C.ITEM_RESTORED), failed=ended.count(C.ITEM_RESTORE_FAILED))

    @staticmethod
    def _step(target: Target, restore_one: Callable[[Target], RestoreStep]) -> RestoreItem:
        result = restore_one(target)
        if not result.ok:
            logger.warning("offload_restore_batch_target_failed", kind=target.kind, target=target.id, code=result.code)
        return RestoreItem(target.kind, target.id, C.ITEM_RESTORED if result.ok else C.ITEM_RESTORE_FAILED, result.code, result.detail[:300], result.conversations, result.bytes)

    def get(self, batch_id: str) -> Optional[RestoreBatch]:
        with self._lock:
            found = self._batches.get(batch_id)
            return copy.deepcopy(found) if found is not None else None

    def latest(self) -> Optional[RestoreBatch]:
        with self._lock:
            return copy.deepcopy(self._batches[self._latest]) if self._latest else None

    def stop(self, batch_id: str) -> Optional[RestoreBatch]:
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
            if running:
                self._stop.set()
        return running

    def wait_stopped(self, seconds: float) -> bool:
        return self._stop.wait(seconds)

    def join(self, timeout: Optional[float] = None) -> bool:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()
