
from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Dict, Optional

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate.handle import ExportCancelled, JobHandle
from src.cplugs.crate.jobs import state
from src.cplugs.sdk import blob_codec as bc

logger = structlog.get_logger()

Notify = Callable[[str, Optional[str]], None]
Work = Callable[[JobHandle], Dict[str, Any]]

TOPIC = "jobs"


class JobBusy(Exception):

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} is running; one crate job runs at a time")
        self.code, self.job_id = "job_busy", job_id


class JobFailed(Exception):

    def __init__(self, code: str, detail: Any) -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


class _Slot:

    def __init__(self, root: Any, rec: state.JobRecord, notify: Notify, clock: Callable[[], float]) -> None:
        self.root, self.rec, self.notify, self.clock = root, rec, notify, clock
        self.pacer = bc.Throttle(K.DUTY)
        self.handle = JobHandle(rec.job_id, on_change=self.changed, pacer=self.pacer)
        self.thread: Optional[threading.Thread] = None
        self._last_push = -math.inf
        self._signature: Any = None

    def changed(self, handle: JobHandle) -> None:
        signature = (handle.phase_name, tuple(handle.temp_paths), handle.publish is not None)
        now = self.clock()
        if signature == self._signature and now - self._last_push < K.PROGRESS_NOTIFY_S:
            return
        self._signature, self._last_push = signature, now
        self.flush()
        self.notify(TOPIC, self.rec.job_id)

    def flush(self) -> None:
        h, rec = self.handle, self.rec
        rec.phase = h.phase_name
        rec.progress = {"done_bytes": h.done_bytes, "total_bytes": h.total_bytes, "files_done": h.files_done,
                        "files_total": h.files_total}
        rec.temp_paths = list(h.temp_paths)
        rec.publish = dict(h.publish) if h.publish else None
        rec.updated_at = time.time()
        state.save(self.root, rec)


_LOCK = threading.Lock()
_SLOT: Optional[_Slot] = None


def running_id() -> Optional[str]:
    with _LOCK:
        return _SLOT.rec.job_id if _SLOT is not None else None


def running_request() -> Optional[Dict[str, Any]]:
    with _LOCK:
        return dict(_SLOT.rec.request) if _SLOT is not None else None


def _finish(slot: _Slot, final: str, *, result: Optional[Dict[str, Any]] = None,
            error: Optional[Dict[str, Any]] = None) -> None:
    global _SLOT
    slot.rec.state, slot.rec.result, slot.rec.error = final, result, error
    try:
        slot.flush()
    except OSError as exc:
        logger.error("crate_job_record_unsaved", job_id=slot.rec.job_id, kind=slot.rec.kind, state=final,
                     error_type=type(exc).__name__, errno=exc.errno)
    finally:
        with _LOCK:
            if _SLOT is slot:
                _SLOT = None
    slot.notify(TOPIC, slot.rec.job_id)


def _run(slot: _Slot, work: Work) -> None:
    try:
        result = work(slot.handle)
    except ExportCancelled:
        _finish(slot, K.STATE_CANCELLED, error={"code": "cancelled", "detail": "the job was cancelled"})
    except JobFailed as exc:
        logger.warning("crate_job_failed", job_id=slot.rec.job_id, kind=slot.rec.kind, code=exc.code)
        _finish(slot, K.STATE_FAILED, error={"code": exc.code, "detail": exc.detail})
    except BaseException as exc:
        logger.error("crate_job_crashed", job_id=slot.rec.job_id, kind=slot.rec.kind, error_type=type(exc).__name__)
        _finish(slot, K.STATE_FAILED, error={"code": K.E_JOB_CRASHED, "detail": type(exc).__name__})
        raise
    else:
        _finish(slot, K.STATE_DONE, result=result)


def start(work_dir: Any, kind: str, request: Dict[str, Any], work: Work, *, notify: Notify,
          clock: Callable[[], float] = time.monotonic) -> str:
    """Start one job on the slot. Blocking only for the first record write. Output: the job id.

    Inputs: work_dir (the plugin folder; records go in its ``jobs``); kind (``constants.KIND_*``); request (what was asked,
      shown in the job view; NEVER an identity); work (``work(handle) -> result``); notify (``ctx.notify``); clock (a
      monotonic clock for push coalescing; a test patches it).
    Raises: JobBusy; OSError (the record could not be written; nothing started).
    Example: start(env.work, 'verify', {'bundle_id': b}, lambda h: {...}, notify=ctx.notify)
    """
    global _SLOT
    root = state.jobs_dir(work_dir)
    with _LOCK:
        if _SLOT is not None:
            raise JobBusy(_SLOT.rec.job_id)
        now = time.time()
        rec = state.JobRecord(job_id=state.new_job_id(now), kind=kind, created_at=now, updated_at=now,
                              request=dict(request))
        state.save(root, rec)
        slot = _Slot(root, rec, notify, clock)
        slot.thread = threading.Thread(target=_run, args=(slot, work), name=f"crate-{rec.job_id}", daemon=True)
        _SLOT = slot
    notify(TOPIC, rec.job_id)
    slot.thread.start()
    return rec.job_id


def cancel(job_id: str) -> bool:
    with _LOCK:
        slot = _SLOT if _SLOT is not None and _SLOT.rec.job_id == job_id else None
    if slot is None:
        return False
    slot.handle.cancel()
    slot.pacer.cancel()
    return True


def cancel_all() -> Optional[str]:
    job_id = running_id()
    if job_id is not None:
        cancel(job_id)
    return job_id


def join(timeout: float) -> bool:
    with _LOCK:
        thread = _SLOT.thread if _SLOT is not None else None
    if thread is None:
        return True
    thread.join(timeout)
    return not thread.is_alive()
