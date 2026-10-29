
from __future__ import annotations

import os
import threading
from typing import Callable, Dict, Iterable, Optional, Tuple, TypeVar

Record = TypeVar("Record")

Signature = Tuple[int, int, int, int]


def _signature(path: str) -> Optional[Signature]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class RegistryFileCache:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kept: Dict[str, Tuple[Signature, object]] = {}

    def load(self, path: str, name: str, loader: Callable[[str, str], Record],
             keep: Callable[[Record], bool]) -> Record:
        signature = _signature(path)
        if signature is not None:
            with self._lock:
                hit = self._kept.get(path)
            if hit is not None and hit[0] == signature:
                return hit[1]  # type: ignore[return-value]
        record = loader(path, name)
        with self._lock:
            if signature is not None and keep(record):
                self._kept[path] = (signature, record)
            else:
                self._kept.pop(path, None)
        return record

    def retain_only(self, paths: Iterable[str]) -> None:
        live = set(paths)
        with self._lock:
            for path in [p for p in self._kept if p not in live]:
                del self._kept[path]
