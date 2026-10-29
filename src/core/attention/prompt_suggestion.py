
from __future__ import annotations

import re
import threading
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from src.core.attention.pane_prompt_box import _is_rule_line

PROMPT_GLYPH = "❯"

_CSI = re.compile(r"\x1b\[([0-9;:?]*)([@-~])")


def input_row(lines: Sequence[str]) -> Optional[Tuple[int, str]]:
    for row in range(len(lines) - 1, -1, -1):
        body = lines[row].lstrip()
        if not body.startswith(PROMPT_GLYPH):
            continue
        above = row - 1
        while above >= 0 and not lines[above].strip():
            above -= 1
        if above >= 0 and _is_rule_line(lines[above]):
            return row, body[len(PROMPT_GLYPH):].replace("\xa0", " ").strip()
        return None
    return None


def _apply_sgr(params: str, dim: bool, inverse: bool) -> Tuple[bool, bool]:
    codes = [p for p in params.replace(":", ";").split(";")] or [""]
    index = 0
    while index < len(codes):
        code = codes[index]
        if code in ("", "0"):
            dim = inverse = False
        elif code == "2":
            dim = True
        elif code == "22":
            dim = False
        elif code == "7":
            inverse = True
        elif code == "27":
            inverse = False
        elif code in ("38", "48", "58"):
            mode = codes[index + 1] if index + 1 < len(codes) else ""
            index += 2 if mode == "5" else 4 if mode == "2" else 1
        index += 1
    return dim, inverse


def suggestion_from_line(line: str) -> Optional[str]:
    dim = inverse = seen_glyph = False
    words = []
    position = 0
    while position < len(line):
        match = _CSI.match(line, position)
        if match:
            if match.group(2) == "m":
                dim, inverse = _apply_sgr(match.group(1), dim, inverse)
            position = match.end()
            continue
        char = line[position]
        position += 1
        if char == "\x1b":
            continue
        if not seen_glyph:
            seen_glyph = char == PROMPT_GLYPH
            continue
        if char.isspace() or char == "\xa0":
            words.append(" ")
            continue
        if not (dim or inverse):
            return None
        words.append(char)
    text = " ".join("".join(words).split())
    return text or None


class PromptSuggestions:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kept: Dict[str, str] = {}

    def update(self, session_id: str, *, idle: bool, screen: Optional[str],
               read_row: Callable[[int], Optional[str]]) -> Optional[str]:
        if not idle:
            self.forget(session_id)
            return None
        if screen is None:
            return self.current(session_id)
        found = input_row(screen.splitlines())
        if found is None or not found[1]:
            self.forget(session_id)
            return None
        row, plain = found
        line = read_row(row)
        suggestion = suggestion_from_line(line) if line is not None else None
        if suggestion is not None and suggestion != " ".join(plain.split()):
            suggestion = None
        with self._lock:
            if suggestion is None:
                self._kept.pop(session_id, None)
            else:
                self._kept[session_id] = suggestion
        return suggestion

    def current(self, session_id: str) -> Optional[str]:
        with self._lock:
            return self._kept.get(session_id)

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._kept.pop(session_id, None)

    def retain_only(self, session_ids: Iterable[str]) -> None:
        keep = set(session_ids)
        with self._lock:
            self._kept = {k: v for k, v in self._kept.items() if k in keep}
