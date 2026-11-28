
from __future__ import annotations

import threading
import time

import pytest

from src.core.deepsearch import fallback_hook as fb
from src.core.deepsearch import vault_lookup as vl

CONV = "aaaaaaaa-1111-2222-3333-444444444444"
PATH = "/x/.claude/projects/-p/" + CONV + ".jsonl"


class _Hung:

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0

    def files(self, conversation_id: str):
        self.calls += 1
        self.release.wait(10)
        return []


class _Holds:

    def __init__(self, held) -> None:
        self.held = held

    def files(self, conversation_id: str):
        return [object()] if conversation_id in self.held else []


@pytest.fixture(autouse=True)
def _clean():
    fb.unregister("a")
    vl.reset()
    yield
    fb.unregister("a")
    vl.reset()


def _lookup_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "deepsearch-vault-lookup" and t.is_alive())


def test_a_hung_vault_then_a_hundred_removals_start_at_most_one_thread_and_answer_fast(monkeypatch):
    monkeypatch.setattr(vl, "LOOKUP_TIMEOUT_SECONDS", 0.05)
    hung = _Hung()
    fb.register("a", hung)
    try:
        assert vl.lookup("c0") is None
        started = time.monotonic()
        answers = [vl.lookup(f"c{i}") for i in range(1, 101)]
        elapsed = time.monotonic() - started
        assert set(answers) == {None}
        assert elapsed < 0.5
        assert hung.calls == 1 and _lookup_threads() <= 1
    finally:
        hung.release.set()


def test_the_breaker_closes_after_its_window_and_a_healed_vault_answers(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(vl, "_clock", lambda: now[0])
    monkeypatch.setattr(vl, "LOOKUP_TIMEOUT_SECONDS", 0.05)
    hung = _Hung()
    fb.register("a", hung)
    assert vl.lookup("c0") is None
    hung.release.set()
    for t in threading.enumerate():
        if t.name == "deepsearch-vault-lookup":
            t.join(2)
    fb.register("a", _Holds(["c1"]))
    assert vl.lookup("c1") is None
    now[0] += vl.BREAKER_SECONDS + 1
    assert vl.lookup("c1") is True


def test_a_kept_answer_is_not_read_by_a_removal_of_another_file():
    fb.register("a", _Holds([CONV]))
    vl.prepare(CONV, PATH)
    assert vl.take(CONV, "/x/.claude/projects/-q/" + CONV + ".jsonl") is None
    assert vl.take(CONV, PATH) is True


def test_a_kept_answer_is_read_once_by_its_own_removal():
    fb.register("a", _Holds([CONV]))
    vl.prepare(CONV, PATH)
    assert vl.take(CONV, PATH) is True
    assert vl.take(CONV, PATH) is None


def test_a_kept_answer_expires(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(vl, "_clock", lambda: now[0])
    fb.register("a", _Holds([CONV]))
    vl.prepare(CONV, PATH)
    now[0] += vl.ANSWER_TTL_SECONDS + 1
    assert vl.take(CONV, PATH) is None
