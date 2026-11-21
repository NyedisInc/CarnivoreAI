
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.safe_io import realpath_memo


@pytest.fixture
def spy(monkeypatch):
    realpath_memo.clear()
    calls: list[str] = []
    clock = [1000.0]
    real = os.path.realpath
    monkeypatch.setattr(realpath_memo.os.path, "realpath", lambda p, *a, **k: calls.append(p) or real(p, *a, **k))
    monkeypatch.setattr(realpath_memo.time, "monotonic", lambda: clock[0])
    yield calls, clock
    realpath_memo.clear()


def test_a_repeat_call_does_not_resolve_again_and_past_the_bound_it_does(spy, tmp_path: Path) -> None:
    calls, clock = spy
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    assert realpath_memo.realpath(str(link)) == str(target.resolve())
    assert realpath_memo.realpath(link) == str(target.resolve())
    assert calls.count(str(link)) == 1
    other = tmp_path / "other"
    other.mkdir()
    link.unlink()
    link.symlink_to(other)
    assert realpath_memo.realpath(str(link)) == str(target.resolve())
    clock[0] += realpath_memo.TTL_S + 1
    assert realpath_memo.realpath(str(link)) == str(other.resolve())
    assert calls.count(str(link)) == 2


def test_the_memo_stays_bounded(spy) -> None:
    for i in range(realpath_memo.MAX_ENTRIES + 10):
        realpath_memo.realpath(f"/nonexistent-{i}")
    assert len(realpath_memo._entries) <= realpath_memo.MAX_ENTRIES


def test_a_relative_path_is_never_remembered(spy, tmp_path: Path, monkeypatch) -> None:
    calls, _clock = spy
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    monkeypatch.chdir(tmp_path / "a")
    first = realpath_memo.realpath("x")
    monkeypatch.chdir(tmp_path / "b")
    assert realpath_memo.realpath("x") != first
    assert calls.count("x") == 2 and "x" not in realpath_memo._entries
