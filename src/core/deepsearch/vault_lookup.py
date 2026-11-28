
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import structlog

from src.core.transcript_manifest import gone_guard

logger = structlog.get_logger(__name__)

LOOKUP_TIMEOUT_SECONDS: float = 5.0
BREAKER_SECONDS: float = 60.0
ANSWER_TTL_SECONDS: float = 30.0
MAX_KEPT: int = 256

_lock = threading.Lock()
_answers: Dict[str, Tuple[str, Optional[bool], float]] = {}
_blocked_until: float = 0.0
_inflight: Optional[threading.Thread] = None
_clock: Callable[[], float] = time.monotonic


def lookup(conversation_id: str) -> Optional[bool]:
    global _blocked_until, _inflight
    box: List[Optional[bool]] = []

    def work() -> None:
        box.append(gone_guard.held_by_vault(conversation_id, ask_while_booting=True))

    with _lock:
        if _clock() < _blocked_until:
            return None
        if _inflight is not None and _inflight.is_alive():
            _blocked_until = _clock() + BREAKER_SECONDS
            return None
        worker = threading.Thread(target=work, name="deepsearch-vault-lookup", daemon=True)
        _inflight = worker
        worker.start()
    worker.join(LOOKUP_TIMEOUT_SECONDS)
    if worker.is_alive() or not box:
        with _lock:
            _blocked_until = _clock() + BREAKER_SECONDS
        logger.warning("deepsearch_vault_lookup_unanswered", conversation_id=conversation_id, timed_out=worker.is_alive(),
                       breaker_seconds=BREAKER_SECONDS)
        return None
    return box[0]


def reset() -> None:
    global _blocked_until, _inflight
    with _lock:
        _answers.clear()
        _blocked_until = 0.0
        _inflight = None


def prepare(conversation_id: str, path: str) -> None:
    answer = lookup(conversation_id)
    with _lock:
        now = _clock()
        for key in [k for k, (_, _, at) in _answers.items() if now - at > ANSWER_TTL_SECONDS]:
            del _answers[key]
        if len(_answers) >= MAX_KEPT:
            _answers.pop(next(iter(_answers)))
        _answers[path] = (conversation_id, answer, now)


def take(conversation_id: str, path: str) -> Optional[bool]:
    with _lock:
        kept = _answers.pop(path, None)
        if kept is None or kept[0] != conversation_id or _clock() - kept[2] > ANSWER_TTL_SECONDS:
            return None
        return kept[1]
