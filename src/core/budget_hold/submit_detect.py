
from __future__ import annotations

from typing import Tuple

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"

SUBMIT_SEQUENCES: Tuple[str, ...] = ("\r", "\n", "\x1bOM", "\x1b[13u")
PASTE_SUBMIT_CHARS: Tuple[str, ...] = ("\r", "\n")


def _partial_tail(text: str) -> str:
    keep = ""
    for token in (PASTE_START, PASTE_END) + tuple(s for s in SUBMIT_SEQUENCES if len(s) > 1):
        for n in range(min(len(token) - 1, len(text)), 0, -1):
            if text.endswith(token[:n]) and n > len(keep):
                keep = token[:n]
                break
    return keep


class SubmitDetector:

    def __init__(self) -> None:
        self._in_paste = False
        self._tail = ""

    def split(self, text: str) -> Tuple[str, bool]:
        buf = self._tail + text
        skip = len(self._tail)
        self._tail = ""
        i = 0
        while i < len(buf):
            if self._in_paste:
                end = buf.find(PASTE_END, i)
                payload = buf[i:] if end < 0 else buf[i:end]
                if any(c in payload for c in PASTE_SUBMIT_CHARS):
                    return self._cut(buf, i, skip, True)
                if end < 0:
                    self._tail = _partial_tail(buf)
                    return text, False
                self._in_paste = False
                i = end + len(PASTE_END)
                continue
            if buf.startswith(PASTE_START, i):
                end = buf.find(PASTE_END, i + len(PASTE_START))
                payload = buf[i + len(PASTE_START):] if end < 0 else buf[i + len(PASTE_START):end]
                if any(c in payload for c in PASTE_SUBMIT_CHARS):
                    return self._cut(buf, i, skip, False)
                if end < 0:
                    self._in_paste = True
                    return text, False
                i = end + len(PASTE_END)
                continue
            for seq in SUBMIT_SEQUENCES:
                if buf.startswith(seq, i):
                    return self._cut(buf, i, skip, False)
            i += 1
        self._tail = _partial_tail(buf)
        return text, False

    def _cut(self, buf: str, at: int, skip: int, in_paste: bool) -> Tuple[str, bool]:
        at = max(at, skip)
        pos = at
        while True:
            marker = PASTE_END if in_paste else PASTE_START
            found = buf.find(marker, pos)
            if found < 0:
                break
            in_paste = not in_paste
            pos = found + len(marker)
        self._in_paste = in_paste
        self._tail = ""
        return buf[skip:at], True
