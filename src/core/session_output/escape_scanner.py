
from __future__ import annotations

from typing import List, NamedTuple, Optional

ESC, BEL, OSC_START, ST = 0x1B, 0x07, b"\x1b]", b"\x1b\\"
MAX_CODE_BYTES = 4096
MAX_EVENTS_PER_FEED = 16
_WANTED = (b"9", b"777", b"99", b"3008")
_PREFIX_PEEK = 5
STATUS_EVENTS = frozenset({"busy", "idle", "waiting", "done"})

_NORMAL, _ESC, _OSC, _OSC_ESC, _SKIP, _SKIP_ESC = range(6)


class Event(NamedTuple):

    kind: str
    title: str = ""
    body: str = ""
    percent: Optional[int] = None


_BELL = Event("bell")


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


class EscapeScanner:

    __slots__ = ("_state", "_buf", "_kitty_title", "dropped", "_out")

    def __init__(self) -> None:
        self._state = _NORMAL
        self._buf = bytearray()
        self._kitty_title = ""
        self.dropped = 0
        self._out: List[Event] = []

    def _emit(self, event: Event) -> None:
        if len(self._out) < MAX_EVENTS_PER_FEED:
            self._out.append(event)
        else:
            self.dropped += 1

    def feed(self, data: bytes) -> List[Event]:
        if self._state == _NORMAL and data.find(OSC_START) < 0 and data.find(b"\x07") < 0:
            if data.endswith(b"\x1b"):
                self._state = _ESC
            return []
        self._out = []
        i, n = 0, len(data)
        while i < n:
            state = self._state
            if state == _NORMAL:
                osc = data.find(OSC_START, i)
                stop = osc if osc >= 0 else n
                bells = data.count(b"\x07", i, stop)
                if bells:
                    take = min(bells, max(MAX_EVENTS_PER_FEED - len(self._out), 0))
                    self._out.extend([_BELL] * take)
                    self.dropped += bells - take
                if osc >= 0:
                    self._start_osc()
                    i = osc + 2
                else:
                    if data[n - 1] == ESC:
                        self._state = _ESC
                    return self._out
            elif state == _ESC:
                if data[i] == 0x5D:
                    self._start_osc()
                    i += 1
                else:
                    self._state = _NORMAL
            elif state in (_OSC, _SKIP):
                i = self._osc_bytes(data, i, n, state == _SKIP)
            else:
                skipping = state == _SKIP_ESC
                if data[i] == 0x5C:
                    if not skipping:
                        self._finish()
                    self._state = _NORMAL
                    i += 1
                else:
                    self._buf.clear()
                    self._state = _ESC
        return self._out

    def _start_osc(self) -> None:
        self._buf.clear()
        self._state = _OSC

    def _osc_bytes(self, data: bytes, i: int, n: int, skipping: bool) -> int:
        bel, esc = data.find(b"\x07", i), data.find(b"\x1b", i)
        ends = [p for p in (bel, esc) if p >= 0]
        end = min(ends) if ends else n
        if not skipping:
            room = MAX_CODE_BYTES - len(self._buf)
            self._buf += data[i:min(end, i + room + 1)]
            if len(self._buf) > MAX_CODE_BYTES:
                self._buf.clear()
                skipping, self._state = True, _SKIP
            elif not self._wanted():
                self._buf.clear()
                skipping, self._state = True, _SKIP
        if end == n:
            return n
        if data[end] == BEL:
            if not skipping:
                self._finish()
            self._state = _NORMAL
        else:
            self._state = _SKIP_ESC if skipping else _OSC_ESC
        return end + 1

    def _wanted(self) -> bool:
        head = bytes(self._buf[:_PREFIX_PEEK])
        semi = head.find(b";")
        if semi < 0:
            return len(head) < _PREFIX_PEEK and any(w.startswith(head) for w in _WANTED)
        return head[:semi] in _WANTED

    def _finish(self) -> None:
        payload = bytes(self._buf)
        self._buf.clear()
        code, _, rest = payload.partition(b";")
        if code == b"9":
            if rest.startswith(b"4;") or rest == b"4":
                parts = rest.split(b";")
                state = parts[1][:1].decode("ascii", "replace") if len(parts) > 1 and parts[1] else "0"
                pct = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
                if state in "01234" and state:
                    self._emit(Event("progress", state, "", min(pct, 100) if pct is not None else None))
            elif rest:
                self._emit(Event("notify", "", _text(rest)))
        elif code == b"3008":
            fields = dict(kv.partition(b"=")[::2] for kv in rest.split(b";") if kv)
            event = fields.get(b"event", b"").decode("ascii", "replace")
            if event in STATUS_EVENTS:
                self._emit(Event("status", event, _text(fields.get(b"id", b""))[:256]))
        elif code == b"777":
            kind, _, tail = rest.partition(b";")
            if kind == b"notify":
                title, _, body = tail.partition(b";")
                self._emit(Event("notify", _text(title), _text(body)))
        elif code == b"99":
            meta, _, text = rest.partition(b";")
            keys = dict(kv.partition(b"=")[::2] for kv in meta.split(b":") if kv)
            if keys.get(b"p", b"title") == b"body":
                self._emit(Event("notify", self._kitty_title, _text(text)))
                self._kitty_title = ""
            elif keys.get(b"d") == b"0":
                self._kitty_title = _text(text)[:MAX_CODE_BYTES]
            else:
                self._emit(Event("notify", _text(text), ""))
                self._kitty_title = ""
