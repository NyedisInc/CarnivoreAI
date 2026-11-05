
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol


class StatsStoreLike(Protocol):

    state_dir: Path
    db_path: Path

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        pass

    def connect_read(self) -> sqlite3.Connection:
        pass

    def discard_read(self) -> None:
        pass

    def revision(self) -> int:
        pass
