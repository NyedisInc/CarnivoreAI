
from __future__ import annotations

import sqlite3


def count_connects(monkeypatch) -> list:
    opened: list = []
    real = sqlite3.connect

    def counting(*args, **kwargs):
        opened.append(str(args[0]) if args else "")
        return real(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    return opened


def opens_of(opened: list, name: str) -> int:
    return sum(1 for target in opened if name in target)
