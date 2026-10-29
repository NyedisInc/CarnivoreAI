
from __future__ import annotations

from typing import Sequence

from src.core.work.work_ladder.w1 import W1
from src.core.work.work_ladder.w2 import W2
from src.core.work.work_ladder.w3 import W3

MIGRATIONS: Sequence[str] = (W1, W2, W3)

VERSION = len(MIGRATIONS)

VERSION_KEY = "work_ladder"


def statements(script: str) -> list:
    import sqlite3  # noqa: PLC0415

    out, buffer = [], []
    for line in script.splitlines():
        if not line.strip() and not buffer:
            continue
        buffer.append(line)
        if line.rstrip().endswith(";") and sqlite3.complete_statement("\n".join(buffer)):
            out.append("\n".join(buffer).strip())
            buffer = []
    if any(part.strip() for part in buffer):
        raise ValueError("a rung ends inside a statement")
    return out
