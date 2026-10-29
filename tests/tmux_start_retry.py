
from __future__ import annotations

import subprocess
import time
from typing import Any, Callable, List, Tuple

__all__ = [
    "RETRYABLE_SUBPROCESS_LABELS",
    "is_tmux_start_argv",
    "run_tmux_start_with_retry",
]

_START_SUBCOMMANDS: Tuple[str, ...] = ("new-session", "start-server")

_FAILURE_SIGNATURE: str = "server exited unexpectedly"

_RETRY_ATTEMPTS: int = 3

_RETRY_BACKOFF_S: Tuple[float, ...] = (0.2, 0.5)

RETRYABLE_SUBPROCESS_LABELS = frozenset(
    {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output"}
)


def is_tmux_start_argv(argv: List[str]) -> bool:
    return any(tok in _START_SUBCOMMANDS for tok in argv)


def _failure_text(outcome: Any) -> str:
    parts: List[str] = []
    for attr in ("stdout", "stderr", "output"):
        value = getattr(outcome, attr, None)
        if not value:
            continue
        parts.append(value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value))
    return "\n".join(parts)


def _is_transient_start_failure(outcome: Any) -> bool:
    return _FAILURE_SIGNATURE in _failure_text(outcome).lower()


def run_tmux_start_with_retry(original: Callable, args: tuple, kwargs: dict) -> Any:
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        is_last = attempt == _RETRY_ATTEMPTS
        try:
            result = original(*args, **kwargs)
        except subprocess.CalledProcessError as exc:
            if not is_last and _is_transient_start_failure(exc):
                time.sleep(_RETRY_BACKOFF_S[attempt - 1])
                continue
            raise
        returncode = result if isinstance(result, int) else getattr(result, "returncode", 0)
        if returncode and not is_last and _is_transient_start_failure(result):
            time.sleep(_RETRY_BACKOFF_S[attempt - 1])
            continue
        return result
    raise AssertionError("unreachable: the loop above always returns or raises")
