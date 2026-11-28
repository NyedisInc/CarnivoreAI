
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Tuple

import structlog

from src.core.auto_sleep.pane_ports import pid_holds_listener
from src.core.conversation_writers import MeasureError

logger = structlog.get_logger()

TTL_SECONDS: float = 30.0

MAX_ENTRIES: int = 512


class ServerProbe:

    def __init__(
        self,
        holds_listener: Callable[[int], bool] = pid_holds_listener,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._holds = holds_listener
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: Dict[Tuple[int, str], Tuple[float, bool]] = {}

    def is_server(self, shell_pid: int, command: str, tree: List[int]) -> bool:
        key = (shell_pid, command)
        now = self._clock()
        with self._lock:
            hit = self._seen.get(key)
        if hit is not None and now - hit[0] < TTL_SECONDS:
            return hit[1]
        try:
            answer = any(self._holds(pid) for pid in tree)
        except (MeasureError, OSError) as exc:
            logger.warning("background_server_probe_unavailable", shell_pid=shell_pid, error=str(exc))
            answer = hit[1] if hit is not None else False
        with self._lock:
            self._seen[key] = (now, answer)
            if len(self._seen) > MAX_ENTRIES:
                for old in sorted(self._seen, key=lambda k: self._seen[k][0])[: MAX_ENTRIES // 2]:
                    del self._seen[old]
        return answer


__all__ = ["MAX_ENTRIES", "ServerProbe", "TTL_SECONDS"]
