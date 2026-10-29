
from __future__ import annotations

import pytest

from src.core import session_transcript_presence as presence

UUID = "deab833f-3c01-4d80-8340-84d081bb38fa"


@pytest.fixture(autouse=True)
def empty_cache():
    presence._cache.clear()
    yield
    presence._cache.clear()


@pytest.fixture
def measured(monkeypatch):
    calls: list = []
    real = presence._measure_presence

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(presence, "_measure_presence", counting)
    return calls


def test_a_cached_answer_is_reused_within_the_ttl_and_remeasured_after(tmp_path, measured, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(presence.time, "monotonic", lambda: clock[0])
    (tmp_path / "proj").mkdir()
    for _ in range(3):
        assert presence.conversation_presence(UUID, corpus_root=tmp_path, cache_seconds=2.0).missing
    assert len(measured) == 1
    clock[0] += 2.5
    presence.conversation_presence(UUID, corpus_root=tmp_path, cache_seconds=2.0)
    assert len(measured) == 2


def test_a_just_created_transcript_is_seen_once_the_short_ttl_passes(tmp_path, measured, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(presence.time, "monotonic", lambda: clock[0])
    (tmp_path / "proj").mkdir()
    assert presence.conversation_presence(UUID, corpus_root=tmp_path, cache_seconds=2.0).missing
    (tmp_path / "proj" / f"{UUID}.jsonl").write_text("{}\n")
    clock[0] += 2.1
    assert presence.conversation_presence(UUID, corpus_root=tmp_path, cache_seconds=2.0).outcome == presence.CONVERSATION_PRESENT


def test_the_default_never_caches_so_a_resume_preflight_always_measures(tmp_path, measured):
    (tmp_path / "proj").mkdir()
    assert presence.conversation_presence(UUID, corpus_root=tmp_path).missing
    (tmp_path / "proj" / f"{UUID}.jsonl").write_text("{}\n")
    assert presence.conversation_presence(UUID, corpus_root=tmp_path).outcome == presence.CONVERSATION_PRESENT
    assert len(measured) == 2
