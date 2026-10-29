
from __future__ import annotations

import json
import sqlite3
import threading

from src.cplugs.host import activity_log, state


def _write(state_dir, enabled: bool) -> None:
    path = state.state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "cplugs": {"x": {"enabled": enabled, "grants": [], "revision": 1}}}))


def test_state_file_is_parsed_once_and_again_only_after_it_changes(tmp_path, monkeypatch):
    _write(tmp_path, True)
    parses: list = []
    real_loads = json.loads
    monkeypatch.setattr(state.json, "loads", lambda text: parses.append(1) or real_loads(text))
    state._file_cache.clear()
    for _ in range(5):
        assert state.stored_enabled(tmp_path, "x") is True
    assert len(parses) == 1
    _write(tmp_path, False)
    assert state.stored_enabled(tmp_path, "x") is False
    assert len(parses) == 2


def test_activity_record_reuses_one_connection_per_thread(tmp_path, monkeypatch):
    connects: list = []
    real_connect = sqlite3.connect
    monkeypatch.setattr(activity_log.sqlite3, "connect", lambda *a, **k: connects.append(1) or real_connect(*a, **k))
    log = activity_log.ActivityLog(tmp_path)
    for i in range(10):
        log.record("p", method="m", permission="perm", target=f"t{i}")
    assert len(connects) == 1
    assert len(log.recent("p")) == 10
    connects.clear()
    other: list = []
    thread = threading.Thread(target=lambda: (log.record("p", method="m", permission="perm", target="z"), other.append(1)))
    thread.start()
    thread.join()
    assert len(connects) == 1, "a second thread must get its own connection, never share one"
