
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


def is_dataless_stat(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_flags", 0) & SF_DATALESS)


def is_dataless_file(path: Path) -> bool:
    try:
        return is_dataless_stat(os.stat(path))
    except OSError:
        return False


def deadlock_paths(exc: BaseException) -> List[str]:
    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, OSError) and exc.filename:
            return [str(exc.filename)]
        exc, seen = exc.__cause__, seen + 1
    return []
