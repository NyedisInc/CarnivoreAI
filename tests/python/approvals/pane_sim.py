
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "approvals"
_ROW = re.compile(r"^(\s*)(?:([❯›])\s)?(\s*)(\d+)\.\s")
UP, DOWN, ENTER, ESC = "\x1b[A", "\x1b[B", "\r", "\x1b"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


class PaneSim:

    def __init__(self, screen: str) -> None:
        self.lines = screen.split("\n")
        self.rows = [i for i, line in enumerate(self.lines) if _ROW.match(line)]
        self.glyph, self.base, self.cursor = "❯", "", 0
        for n, i in enumerate(self.rows):
            m = _ROW.match(self.lines[i])
            if m and m.group(2):
                self.glyph, self.base, self.cursor = m.group(2), m.group(1), n
        self.keys: List[str] = []
        self.pressed: Optional[int] = None
        self.dismissed = False

    def render(self) -> str:
        out = list(self.lines)
        for n, i in enumerate(self.rows):
            rest = _ROW.sub(lambda m: f"{m.group(4)}. ", out[i], count=1)
            out[i] = f"{self.base}{self.glyph} {rest}" if n == self.cursor else f"{self.base}  {rest}"
        return "\n".join(out)

    async def capture(self) -> str:
        return self.render()

    async def send(self, key: str) -> None:
        self.keys.append(key)
        if key == UP:
            self.cursor = max(0, self.cursor - 1)
        elif key == DOWN:
            self.cursor = min(len(self.rows) - 1, self.cursor + 1)
        elif key == ENTER:
            self.pressed = self.cursor
        elif key == ESC:
            self.dismissed = True

    def move_cursor(self, n: int) -> None:
        self.cursor = n
