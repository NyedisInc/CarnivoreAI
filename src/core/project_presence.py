
from __future__ import annotations

import errno
import os
import stat as stat_module
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from src.core.db_models import (
    PROJECT_PRESENCE_MISSING,
    PROJECT_PRESENCE_PRESENT,
    PROJECT_PRESENCE_UNCHECKED,
    PROJECT_PRESENCE_UNREACHABLE,
)
from src.core.hosts.identity import is_remote_root
from src.core.trail_entry import utc_now

DEFAULT_STAT_TIMEOUT_SECONDS = 3.0

StatFn = Callable[[str], "os.stat_result"]


@dataclass(frozen=True)
class PresenceResult:

    presence: str
    detail: Optional[str]
    checked_at: str


def _stat_with_timeout(
    path: str, timeout_seconds: float = DEFAULT_STAT_TIMEOUT_SECONDS
) -> os.stat_result:
    outcome: dict = {}

    def _run() -> None:
        try:
            outcome["value"] = os.stat(path)
        except OSError as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise TimeoutError(
            f"stat({path!r}) did not return within {timeout_seconds}s - "
            "treating the volume as unreachable rather than waiting "
            "indefinitely"
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def check_presence(root: str, *, stat_fn: Optional[StatFn] = None) -> PresenceResult:
    checked_at = utc_now()
    if is_remote_root(root):
        return PresenceResult(PROJECT_PRESENCE_UNCHECKED,
                              "on a remote host; not measured from this machine", checked_at)
    probe = stat_fn or _stat_with_timeout

    try:
        result = probe(root)
    except TimeoutError as exc:
        return PresenceResult(
            PROJECT_PRESENCE_UNREACHABLE, f"TIMEOUT: {exc}", checked_at
        )
    except OSError as exc:
        code = exc.errno
        name = errno.errorcode.get(code, str(code)) if code is not None else "UNKNOWN"
        message = exc.strerror or str(exc)
        if code == errno.ENOENT:
            return PresenceResult(
                PROJECT_PRESENCE_MISSING, f"{name}: {message}", checked_at
            )
        return PresenceResult(
            PROJECT_PRESENCE_UNREACHABLE, f"{name}: {message}", checked_at
        )
    except Exception as exc:  # noqa: BLE001
        return PresenceResult(
            PROJECT_PRESENCE_UNREACHABLE,
            f"{type(exc).__name__}: {exc}",
            checked_at,
        )

    if not stat_module.S_ISDIR(result.st_mode):
        return PresenceResult(
            PROJECT_PRESENCE_UNREACHABLE,
            "ENOTDIR: root exists but is not a directory",
            checked_at,
        )
    return PresenceResult(PROJECT_PRESENCE_PRESENT, None, checked_at)
