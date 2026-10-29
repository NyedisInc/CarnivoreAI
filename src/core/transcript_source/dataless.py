"""Recognise an iCloud placeholder ("dataless" file) a read could not materialize.

Carnivore's server runs with dataless materialization OFF (``docs/tmux-launch-history.md``), so a read of
a placeholder fails at once with EDEADLK ("Resource deadlock avoided") instead of downloading it. That is
transient: the file is in iCloud and a per-file download request brings it back. PURE STDLIB, no project
imports, so the capture path and the save pipeline both use it.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import List

SF_DATALESS: int = 0x40000000


def is_deadlock(exc: BaseException) -> bool:
    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, OSError) and exc.errno == errno.EDEADLK:
            return True
        exc, seen = exc.__cause__, seen + 1
    return False


def is_dataless_file(path: Path) -> bool:
    try:
        return bool(getattr(os.stat(path), "st_flags", 0) & SF_DATALESS)
    except OSError:
        return False


def deadlock_paths(exc: BaseException) -> List[str]:
    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, OSError) and exc.filename:
            return [str(exc.filename)]
        exc, seen = exc.__cause__, seen + 1
    return []
