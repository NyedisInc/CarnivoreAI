
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Hashable, Optional, Sized, Tuple, TypeVar

from src.cplugs.save.vault import constants as K
from src.cplugs.sdk.dir_listing import TRUST_AFTER_NS

T = TypeVar("T")

Stamp = Tuple[int, int, int, int, int]


def file_stamp(path: Path) -> Optional[Stamp]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_ctime_ns, st.st_ino, st.st_dev, st.st_size


def folder_stamp(path: Path) -> Optional[Stamp]:
    stamp = file_stamp(path)
    return None if stamp is None else (*stamp[:4], 0)


def weight_of(value: object) -> int:
    return max(1, len(value)) if isinstance(value, Sized) else 1


class StampMemo:

    def __init__(self, max_entries: int = K.FOLDER_MEMO_MAX_ENTRIES, clock_ns: Callable[[], int] = time.time_ns, *,
                 stamp_of: Callable[[Path], Optional[Stamp]] = folder_stamp, trust_after_ns: int = TRUST_AFTER_NS,
                 weigh: Callable[[object], int] = weight_of) -> None:
        self._max, self._clock_ns, self._stamp_of = max_entries, clock_ns, stamp_of
        self._trust_after_ns, self._weigh = trust_after_ns, weigh
        self._lock = threading.Lock()
        self._items: "OrderedDict[Tuple[str, Hashable], Tuple[Stamp, object, int]]" = OrderedDict()
        self._weight = 0

    def get(self, path: Path, key: Hashable, build: Callable[[], T]) -> T:
        stamp = self._stamp_of(path)
        if stamp is None:
            return build()
        slot = (str(path), key)
        with self._lock:
            hit = self._items.get(slot)
            if hit is not None and hit[0] == stamp:
                self._items.move_to_end(slot)
                return hit[1]  # type: ignore[return-value]
        trusted = self._clock_ns() - max(stamp[0], stamp[1]) > self._trust_after_ns
        value = build()
        if trusted:
            self._store(slot, stamp, value)
        return value

    def _store(self, slot: Tuple[str, Hashable], stamp: Stamp, value: object) -> None:
        weight = self._weigh(value)
        with self._lock:
            old = self._items.pop(slot, None)
            if old is not None:
                self._weight -= old[2]
            self._items[slot] = (stamp, value, weight)
            self._weight += weight
            while self._weight > self._max and len(self._items) > 1:
                _slot, (_stamp, _value, dropped) = self._items.popitem(last=False)
                self._weight -= dropped
