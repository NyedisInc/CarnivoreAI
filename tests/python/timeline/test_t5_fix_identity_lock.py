
from __future__ import annotations

import threading
from pathlib import Path

from src.core.timeline.identity import ConversationIndex

WAIT = 3.0


def test_n6_a_stale_read_in_progress_does_not_block_another_caller() -> None:
    entered, release, answered = threading.Event(), threading.Event(), threading.Event()

    def slow_path() -> Path:
        entered.set()
        release.wait(10)
        return Path("/nonexistent/none.db")

    index = ConversationIndex(slow_path)
    first = threading.Thread(target=index.session_of, args=("c",), daemon=True)
    first.start()
    assert entered.wait(WAIT)
    second = threading.Thread(target=lambda: (index.session_of("c"), answered.set()), daemon=True)
    second.start()
    try:
        assert answered.wait(WAIT), "a caller waited on another caller's sqlite read"
    finally:
        release.set()
        first.join(WAIT)


class _Gated:

    def __init__(self, answers: list, entered: threading.Event, release: threading.Event) -> None:
        self.answers, self.entered, self.release, self.calls = answers, entered, release, 0

    def connect(self, _path: Path, create: bool = True) -> "_Gated":
        return self

    def execute(self, _query: str) -> list:
        number = self.calls
        self.calls += 1
        rows = self.answers[number]
        if number == 0:
            self.entered.set()
            self.release.wait(10)
        return rows

    def close(self) -> None:
        pass


def _index_over(monkeypatch, tmp_path: Path, answers: list) -> tuple:
    import src.core.db as db

    entered, release = threading.Event(), threading.Event()
    gated = _Gated(answers, entered, release)
    monkeypatch.setattr(db, "connect", gated.connect)
    path = tmp_path / "x.db"
    path.write_bytes(b"")
    return ConversationIndex(lambda: path), entered, release


def test_a_slow_older_reload_never_overwrites_a_newer_map(monkeypatch, tmp_path: Path) -> None:
    index, entered, release = _index_over(monkeypatch, tmp_path, [[("c", "old", "running")], [("c", "new", "running")]])
    slow = threading.Thread(target=index._reload, daemon=True)
    slow.start()
    assert entered.wait(WAIT)
    index._reload()
    release.set()
    slow.join(WAIT)
    assert index._map == {"c": "new"}, f"the older reload overwrote the newer map: {index._map}"


def test_clear_during_a_reload_is_not_undone_by_it(monkeypatch, tmp_path: Path) -> None:
    index, entered, release = _index_over(monkeypatch, tmp_path, [[("c", "old", "running")]])
    slow = threading.Thread(target=index._reload, daemon=True)
    slow.start()
    assert entered.wait(WAIT)
    index.clear()
    release.set()
    slow.join(WAIT)
    assert index._map == {}, f"a reload begun before clear wrote its map back: {index._map}"
