"""Atomic write and tolerant read for the small JSON artifacts on disk.

WHY THIS IS ITS OWN MODULE. Two subsystems now publish a "var"-style
liveness artifact beside the state directory: the corpus ingester
(``src/core/corpus_ingest_state.py``) and the database integrity checker
(``src/core/db_integrity.py``). Both need exactly the same two
primitives, and both need them to behave identically, because both hang
a three-outcome verdict off "could this file be read". A second copy of
the write path would be a second chance to get the fsync wrong, and a
second copy of the read path would be a second definition of what
"unreadable" means. So there is one copy, here.

THE WRITE IS THE PATTERN FROM ``Settings.update_settings_config()``:
temp file in the SAME directory, flush, fsync, ``os.replace``. A
half-written artifact is worse than a missing one - a missing one is a
named third outcome and a truncated one parses as garbage.

NEITHER FUNCTION RAISES. Every caller is a fail-soft path that must not
take the server down over a cache file, so the write returns a bool and
the read returns ``None``. The caller turns that ``None`` into a NAMED
state (``never_ran``, ``cannot_determine``), never into a healthy zero.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    class _NoOpLogger:
        """Stand-in logger for the case where structlog is not installed."""

        def __getattr__(self, _name: str) -> Callable[..., None]:
            return lambda *a, **k: None

    logger = _NoOpLogger()


def atomic_write_json(path: Path, payload: dict, *, log_event: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(path.parent),
            prefix=path.name + ".", suffix=".tmp", delete=False,
        )
        try:
            with handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, str(path))
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.warning(
            log_event, path=str(path), error=f"{type(exc).__name__}: {exc}",
        )
        return False


def read_json_object(path: Path, *, log_event: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.debug(
            log_event, path=str(path), error=f"{type(exc).__name__}: {exc}",
        )
        return None
    return data if isinstance(data, dict) else None
