
from __future__ import annotations

from collections import OrderedDict
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.models.websocket import WSMessageType

log = structlog.get_logger(__name__)

FRAME_INTERVAL_SECONDS: float = 1.0
MAX_REMEMBERED: int = 256
EPOCH_CHARS: int = 8

Slot = Tuple[str, str]


@dataclass
class _Held:

    moved: Dict[str, List[Any]] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=dict)
    reset: Set[str] = field(default_factory=set)
    timer: Optional[Any] = None


class FrameCoalescer:

    def __init__(self, send: Callable[[Dict[str, Any]], bool], now: Callable[[], Optional[float]],
                 later: Callable[..., Optional[Any]], interval: float = FRAME_INTERVAL_SECONDS) -> None:
        self._send, self._now, self._later, self._interval = send, now, later, interval
        self._held: Dict[Slot, _Held] = {}
        self._last_sent: "OrderedDict[Slot, float]" = OrderedDict()
        self._seq: "OrderedDict[str, List[Any]]" = OrderedDict()
        self._guard = threading.RLock()
        self.sent = 0

    def add(self, session_uuid: str, conv: str, file_key: str, position: Tuple[int, Optional[str]],
            state: Dict[str, Any], reset: Optional[str]) -> None:
        slot = (session_uuid, conv)
        held = self._held.setdefault(slot, _Held())
        held.moved[file_key] = [position[0], position[1]]
        held.state.update(state)
        if reset:
            held.reset.add(file_key)
        if held.timer is not None:
            return
        now = self._now()
        if now is None:
            return
        wait = self._last_sent.get(slot, float("-inf")) + self._interval - now
        if wait <= 0:
            self._flush(slot, now)
        else:
            held.timer = self._later(wait, self._timer_fired, slot)

    def _timer_fired(self, slot: Slot) -> None:
        held = self._held.get(slot)
        if held is not None:
            held.timer = None
        now = self._now()
        if now is not None:
            self._flush(slot, now)

    def _flush(self, slot: Slot, now: float) -> None:
        held = self._held.pop(slot, None)
        if held is None or not held.moved:
            return
        frame: Dict[str, Any] = {"type": WSMessageType.TIMELINE_DELTA.value, "session_uuid": slot[0], **self._next_seq(slot[0]),
                                 "conv": slot[1], "moved": held.moved, "state": held.state}
        if held.reset:
            frame["reset"] = sorted(held.reset)
        self._send(frame)
        self.sent += 1
        self._last_sent[slot] = now
        self._last_sent.move_to_end(slot)
        while len(self._last_sent) > MAX_REMEMBERED:
            self._last_sent.popitem(last=False)

    def _entry(self, session_uuid: str) -> List[Any]:
        with self._guard:
            entry = self._seq.pop(session_uuid, None) or [uuid.uuid4().hex[:EPOCH_CHARS], 0]
            self._seq[session_uuid] = entry
            while len(self._seq) > MAX_REMEMBERED:
                self._seq.popitem(last=False)
            return entry

    def _next_seq(self, session_uuid: str) -> Dict[str, Any]:
        with self._guard:
            entry = self._entry(session_uuid)
            entry[1] += 1
            return {"epoch": entry[0], "seq": entry[1]}

    def seq_of(self, session_uuid: str) -> int:
        with self._guard:
            entry = self._seq.get(session_uuid)
            return entry[1] if entry else 0

    def epoch_of(self, session_uuid: str) -> str:
        return self._entry(session_uuid)[0]

    def clear(self) -> None:
        for held in self._held.values():
            if held.timer is not None:
                held.timer.cancel()
        self._held.clear()
        self._last_sent.clear()
        with self._guard:
            self._seq.clear()

