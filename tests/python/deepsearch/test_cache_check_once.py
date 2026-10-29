
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from src.core.deepsearch.cache import db as cache_db


def test_concurrent_opens_run_quick_check_once(tmp_path: Path, monkeypatch) -> None:
    key = str(cache_db.cache_path(tmp_path))
    sqlite3.connect(key).close()
    cache_db._checked.discard(key)
    calls: list[str] = []

    def slow_healthy(path: Path) -> bool:
        calls.append(str(path))
        time.sleep(0.3)
        return True

    monkeypatch.setattr(cache_db, "_healthy", slow_healthy)
    threads = [threading.Thread(target=lambda: cache_db.open_cache(tmp_path).close()) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cache_db._checked.discard(key)
    assert len(calls) == 1
