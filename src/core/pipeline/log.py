
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Tuple

import structlog

logger = structlog.get_logger(__name__)

SUMMARY_WINDOW_SECONDS: float = 600.0

_Key = Tuple[str, str, str]
_lock = threading.Lock()
_seen: Dict[_Key, List[float]] = {}


def log_error(event: str, *, plugin: str = "", error: BaseException | str = "",
              clock: Callable[[], float] = time.monotonic, **context: Any) -> bool:
    error_class = type(error).__name__ if isinstance(error, BaseException) else str(error).split(":", 1)[0][:60]
    key: _Key = (event, plugin, error_class)
    now = clock()
    with _lock:
        entry = _seen.get(key)
        if entry is None:
            _seen[key] = [now, 0.0]
            first, repeats = True, 0
        elif now - entry[0] >= SUMMARY_WINDOW_SECONDS:
            first, repeats = True, int(entry[1])
            _seen[key] = [now, 0.0]
        else:
            entry[1] += 1
            return False
    fields = dict(context, plugin=plugin, error_class=error_class, error=str(error)[:300])
    if first and repeats:
        fields["repeats_since_last_line"] = repeats
    logger.warning(event, **fields)
    return True


def reset() -> None:
    with _lock:
        _seen.clear()
