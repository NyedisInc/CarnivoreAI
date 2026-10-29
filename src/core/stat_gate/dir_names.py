from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Dict, Tuple

RACY_WINDOW_NS = 1_000_000_000

MAX_DIRECTORIES = 512

_lock = threading.Lock()
_remembered: "OrderedDict[str, Tuple[Tuple[int, int], Tuple[str, ...]]]" = OrderedDict()


def clear() -> None:
    with _lock:
        _remembered.clear()


def entry_names(directory: "os.PathLike[str] | str", *, files_only: bool = False) -> Tuple[str, ...]:
    path = os.fspath(directory)
    key = "%s\0%d" % (path, files_only)
    stat = os.stat(path)
    signature = (stat.st_ino, stat.st_mtime_ns)
    with _lock:
        known = _remembered.get(key)
        if known is not None and known[0] == signature:
            _remembered.move_to_end(key)
            return known[1]
    with os.scandir(path) as entries:
        names = tuple(sorted(entry.name for entry in entries if not files_only or entry.is_file()))
    if time.time_ns() - stat.st_mtime_ns > RACY_WINDOW_NS:
        with _lock:
            _remembered[key] = (signature, names)
            _remembered.move_to_end(key)
            while len(_remembered) > MAX_DIRECTORIES:
                _remembered.popitem(last=False)
    else:
        with _lock:
            _remembered.pop(key, None)
    return names
