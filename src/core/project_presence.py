"""Four-state filesystem presence for a project root.

Design doc section 4.1 (datastore-and-home-design.md). A project root is
probed with ``os.stat`` and classified into exactly one of four states -
never a fifth, never a collapse of two into one:

  present     - stat succeeded, the path is a directory.
  missing     - ENOENT: the parent resolved, the entry is positively
                absent. The folder was deleted or renamed.
  unreachable - EACCES, EPERM, ELOOP, ENOTDIR, or the probe itself timed
                out. The probe COULD NOT TELL whether the project is
                there. A project on a sleeping external drive, behind a
                permission wall, or at the far end of a symlink loop
                lands here, never in 'missing'.
  unchecked   - not probed yet this run, or the probe raised something
                this module was not written to name. Callers that never
                invoke check_presence() leave a row at this state; it is
                the DDL default (db_models.DDL_PROJECTS), not something
                this module writes itself.

THE CRUX, restated because it is the reason this file exists: telling the
user his project is GONE when the truth is that an external drive is
merely asleep is the same defect as telling him nothing is wrong. Both are
a verdict nobody measured. 'missing' is a claim this module only makes on
positive evidence (ENOENT with the parent chain intact); every other
failure to determine the answer reports 'unreachable' and carries the
errno so the UI can say WHAT could not be measured.
"""

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
    """Probe one project root and classify it into a PresenceResult.

    Description: the ONLY place in this codebase that turns a raw
      ``OSError``/``TimeoutError`` from statting a project root into one
      of the four presence states. ``errno.ENOENT`` is the single code
      that produces 'missing'; every other OSError, and a timeout,
      produces 'unreachable' with the errno name in ``detail`` so the UI
      can say what could not be measured rather than just that something
      failed. A path that exists but is not a directory (e.g. the user
      pointed a project at a file) is reported 'unreachable' with an
      ENOTDIR-shaped detail, matching the errno family this function
      otherwise treats as "could not confirm a usable project root" -
      NOT 'missing', because the entry is demonstrably there.
    Inputs: root (str) - an already-normalised path (see
      project_store.normalize_root(); this function does not call
      expanduser or resolve - it stats exactly the string it is given).
      stat_fn (Callable[[str], os.stat_result] | None) - injected for
      tests so a TimeoutError or a specific errno can be produced
      without needing a real hung mount or a real permission-denied
      directory. Defaults to a timeout-wrapped real ``os.stat``.
    Output: PresenceResult. Never raises - every failure this function
      cannot classify more specifically still resolves to 'unreachable'
      rather than propagating, because a presence probe that can crash
      its caller is worse than one that reports "could not tell".
    Example: check_presence("/Users/example/proj").presence == "present"
    """
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
