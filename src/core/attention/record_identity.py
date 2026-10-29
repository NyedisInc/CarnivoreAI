
from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, Dict, Iterable, Optional, Tuple

import structlog

from src.core.conversation_writers import same_process_start

logger = structlog.get_logger()

REVALIDATE_SECONDS: float = 30.0
PS_TIMEOUT_SECONDS: float = 2.0
PS_PATH: str = "/bin/ps"

Pair = Tuple[int, str]


def read_lstarts(pids: Iterable[int]) -> Optional[Dict[int, str]]:
    """``ps`` lstart for each pid still running, in one call; None when ps could not answer.

    Inputs: pids (iterable of int). Output: dict pid -> lstart text (pids not
      running are simply absent) | None on a failed or timed-out call.
    Example: read_lstarts([os.getpid()]) -> {4242: 'Thu Oct 15 11:52:02 2026'}
    """
    wanted = sorted({int(pid) for pid in pids})
    if not wanted:
        return {}
    try:
        done = subprocess.run(
            [PS_PATH, "-o", "pid=,lstart=", "-p", ",".join(str(pid) for pid in wanted)],
            capture_output=True, timeout=PS_TIMEOUT_SECONDS, check=False, close_fds=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("attention_record_identity_ps_failed", error=str(exc),
                       error_type=type(exc).__name__)
        return None
    found: Dict[int, str] = {}
    for line in done.stdout.decode("utf-8", errors="replace").splitlines():
        head, _, rest = line.strip().partition(" ")
        if head.isdigit() and rest.strip():
            found[int(head)] = rest.strip()
    return found


class RecordIdentity:

    def __init__(self, *, lstarts: Callable[[Iterable[int]], Optional[Dict[int, str]]] = read_lstarts,
                 clock: Callable[[], float] = time.monotonic,
                 revalidate_seconds: float = REVALIDATE_SECONDS) -> None:
        self._lstarts = lstarts
        self._clock = clock
        self._revalidate = revalidate_seconds
        self._lock = threading.Lock()
        self._proofs: Dict[Pair, bool] = {}
        self._checked_at: Optional[float] = None

    def refresh(self, pairs: Iterable[Pair]) -> None:
        live = {(int(pid), str(start)) for pid, start in pairs if pid is not None and start}
        now = self._clock()
        with self._lock:
            due = self._checked_at is None or now - self._checked_at >= self._revalidate
            todo = live if due else {pair for pair in live if pair not in self._proofs}
            self._proofs = {pair: ok for pair, ok in self._proofs.items() if pair in live}
        if not todo:
            return
        found = self._lstarts(pid for pid, _ in todo)
        with self._lock:
            if found is None:
                for pair in todo:
                    self._proofs.pop(pair, None)
                return
            for pid, start in todo:
                ok = pid in found and same_process_start(found[pid], start)
                self._proofs[(pid, start)] = ok
                if not ok:
                    logger.info("attention_record_identity_refused", pid=pid,
                                running=pid in found)
            if due:
                self._checked_at = now

    def proven(self, pid: Optional[int], proc_start: Optional[str]) -> Optional[bool]:
        if pid is None or not proc_start:
            return None
        with self._lock:
            return self._proofs.get((int(pid), str(proc_start)))
