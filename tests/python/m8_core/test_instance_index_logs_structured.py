from __future__ import annotations

import sqlite3

from src.core import session_instance_index as idx


def test_read_failure_logs_with_kwargs_and_returns_an_empty_index(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(idx.logger, "warning", lambda event, **kw: seen.append((event, kw)))
    conn = sqlite3.connect(":memory:")
    result = idx.build_instance_index(conn, socket="cloude", names=["a"])
    assert result.complete is False
    assert seen and seen[0][0] == "instance_index_read_failed"
    assert seen[0][1]["tmux_socket"] == "cloude"
