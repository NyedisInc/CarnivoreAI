
from __future__ import annotations

import json
import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Deque, Dict, Iterable, List

from src.core.transcript_source import constants as K
from src.core.transcript_source.entries import entries_of

_ROLES = ("user", "assistant")
_SLACK = 4
TAIL_WINDOW_BYTES = 256 * 1024
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WRAPPERS = re.compile(
    r"<(system-reminder|local-command-stdout|local-command-caveat|command-name|command-message|command-args)>"
    r".*?</\1>|\[Request interrupted by user[^\]]*\]", re.DOTALL)


@dataclass(frozen=True)
class Message:

    role: str
    text: str

    def as_dict(self) -> Dict[str, str]:
        return {"role": self.role, "text": self.text}


def clean(text: str, limit: int) -> str:
    text = _CONTROL.sub("", _WRAPPERS.sub("", text))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + K.SNIPPET_ELLIPSIS


def _split_role(entry: str) -> tuple:
    for role in _ROLES:
        prefix = f"[{role}] "
        if entry.startswith(prefix):
            return role, entry[len(prefix):]
    return None, ""


def _raw_tail(lines: Iterable[str], keep: int) -> Deque[Message]:
    tail: Deque[Message] = deque()
    for line in lines:
        try:
            rec: Any = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        for entry in entries_of(rec):
            role, text = _split_role(entry)
            if role is None:
                continue
            if role == "assistant" and tail and tail[-1].role == "assistant":
                merged = tail.pop()
                tail.append(Message(role, merged.text + "\n\n" + text))
            else:
                tail.append(Message(role, text))
            while len(tail) > keep:
                tail.popleft()
    return tail


def _finish(raw: Iterable[Message], limit: int, chars: int) -> List[Message]:
    kept = [Message(m.role, clean(m.text, chars)) for m in raw]
    return [m for m in kept if m.text][-limit:]


def recent_from_lines(lines: Iterable[str], limit: int, chars: int = K.MESSAGE_CHARS) -> List[Message]:
    return _finish(_raw_tail(lines, limit + _SLACK), limit, chars)


def _tail_window_lines(handle: BinaryIO, size: int, window: int) -> List[str]:
    start = max(0, size - window)
    handle.seek(start)
    chunk = handle.read(size - start)
    parts = chunk.split(b"\n")
    if start > 0:
        parts = parts[1:]
    return [p.decode("utf-8", errors="replace") for p in parts]


def extract_recent_messages(transcript: Path, limit: int, chars: int = K.MESSAGE_CHARS) -> List[Message]:
    keep = limit + _SLACK
    with open(transcript, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        window = TAIL_WINDOW_BYTES
        while True:
            raw = _raw_tail(_tail_window_lines(handle, size, window), keep + 1)
            if window >= size:
                return _finish(list(raw)[-keep:], limit, chars)
            if len(raw) > keep:
                return _finish(list(raw)[-keep:], limit, chars)
            window *= 2
