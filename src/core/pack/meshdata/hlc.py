
from __future__ import annotations

import threading
import time
from typing import Any, Callable, NamedTuple, Optional

MAX_MS = 2 ** 53 - 1
MAX_CTR = 65535
ACCEPT_LEAD_MS = 300_000
FOLD_LEAD_MS = 60_000
MAX_IID_LEN = 64


class Stamp(NamedTuple):

    ms: int
    ctr: int
    iid: str

    def wire(self) -> list:
        return [self.ms, self.ctr, self.iid]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_stamp(raw: Any) -> Optional[Stamp]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    ms, ctr, iid = raw
    if not (_is_int(ms) and 1 <= ms <= MAX_MS and _is_int(ctr) and 0 <= ctr <= MAX_CTR):
        return None
    if not isinstance(iid, str) or not 1 <= len(iid) <= MAX_IID_LEN or not iid.isprintable():
        return None
    return Stamp(ms, ctr, iid)


def too_far_ahead(stamp: Stamp, now_ms: int) -> bool:
    return stamp.ms > now_ms + ACCEPT_LEAD_MS


def wall_ms() -> int:
    return int(time.time() * 1000)


class Clock:

    def __init__(self, own_iid: str, last: Optional[Stamp], wall: Callable[[], int] = wall_ms) -> None:
        self.own_iid = own_iid
        self.last = last
        self._wall = wall
        self._lock = threading.Lock()

    def now(self) -> Stamp:
        with self._lock:
            wall = min(self._wall(), MAX_MS - 1)
            last = self.last
            if last is None or wall > last.ms:
                stamp = Stamp(wall, 0, self.own_iid)
            elif last.ctr + 1 > MAX_CTR:
                stamp = Stamp(last.ms + 1, 0, self.own_iid)
            else:
                stamp = Stamp(last.ms, last.ctr + 1, self.own_iid)
            self.last = stamp
            return stamp

    def see(self, stamp: Stamp) -> None:
        with self._lock:
            capped = min(stamp, Stamp(min(self._wall(), MAX_MS - FOLD_LEAD_MS) + FOLD_LEAD_MS, 0, ""))
            if self.last is None or capped > self.last:
                self.last = capped

    def after(self, held: Stamp) -> Stamp:
        with self._lock:
            wall = min(self._wall(), MAX_MS - 1)
            last = self.last
            if last is None or wall > last.ms:
                base = Stamp(wall, 0, self.own_iid)
            elif last.ctr + 1 > MAX_CTR:
                base = Stamp(last.ms + 1, 0, self.own_iid)
            else:
                base = Stamp(last.ms, last.ctr + 1, self.own_iid)
            beat = Stamp(held.ms, held.ctr + 1, self.own_iid) if held.ctr + 1 <= MAX_CTR else Stamp(min(held.ms + 1, MAX_MS), 0, self.own_iid)
            self.last = max(base, beat)
            return self.last
