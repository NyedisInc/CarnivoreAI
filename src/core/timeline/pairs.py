
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from src.core.attention.transcript_facts import TranscriptFacts

MAX_PAIRS: int = 512


@dataclass(eq=False)
class Pair:

    legacy: TranscriptFacts
    fold: Optional[TranscriptFacts]
    size: int
    floor_day: Optional[str] = None

    @property
    def raced(self) -> bool:
        return self.fold is None


class PairBook:

    def __init__(self, limit: int = MAX_PAIRS) -> None:
        self._pairs: "OrderedDict[int, Pair]" = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def _put(self, pair: Pair) -> None:
        with self._lock:
            self._pairs[id(pair.legacy)] = pair
            self._pairs.move_to_end(id(pair.legacy))
            while len(self._pairs) > self._limit:
                self._pairs.popitem(last=False)

    def file(self, legacy: TranscriptFacts, fold: TranscriptFacts, size: int) -> None:
        self._put(Pair(legacy, fold, size))

    def mark_raced(self, legacy: TranscriptFacts, size: int) -> None:
        self._put(Pair(legacy, None, size))

    def find(self, legacy: object) -> Optional[Pair]:
        with self._lock:
            pair = self._pairs.get(id(legacy))
            if pair is None or pair.legacy is not legacy:
                return None
            self._pairs.move_to_end(id(legacy))
            return pair

    def clear(self) -> None:
        with self._lock:
            self._pairs.clear()
