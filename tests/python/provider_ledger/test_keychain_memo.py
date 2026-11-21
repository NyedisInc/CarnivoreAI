
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import pytest

from src.core.provider_ledger import keychain_memo


class _Reader:

    def __init__(self, answers: List[Optional[str]]) -> None:
        self.answers = list(answers)
        self.calls = 0

    def __call__(self) -> Optional[str]:
        self.calls += 1
        return self.answers.pop(0) if self.answers else None


@pytest.fixture
def keychain_file(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / keychain_memo.LOGIN_KEYCHAIN_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    keychain_memo.clear()
    yield path
    keychain_memo.clear()


def test_unchanged_keychain_reuses_the_reading(keychain_file) -> None:
    reader = _Reader(["a", "b"])
    assert keychain_memo.remembered_read("svc", "me", reader) == "a"
    assert keychain_memo.remembered_read("svc", "me", reader) == "a"
    assert reader.calls == 1


def test_changed_mtime_reads_again(keychain_file) -> None:
    reader = _Reader(["a", "b"])
    keychain_memo.remembered_read("svc", "me", reader)
    st = keychain_file.stat()
    os.utime(keychain_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert keychain_memo.remembered_read("svc", "me", reader) == "b"
    assert reader.calls == 2


def test_past_max_age_reads_again(keychain_file, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(keychain_memo.time, "monotonic", lambda: clock[0])
    reader = _Reader(["a", "b"])
    keychain_memo.remembered_read("svc", "me", reader)
    clock[0] += keychain_memo.MAX_AGE_SECONDS - 1
    assert keychain_memo.remembered_read("svc", "me", reader) == "a"
    clock[0] += 2
    assert keychain_memo.remembered_read("svc", "me", reader) == "b"
    assert reader.calls == 2


def test_none_is_not_remembered(keychain_file) -> None:
    reader = _Reader([None, "a"])
    assert keychain_memo.remembered_read("svc", "me", reader) is None
    assert keychain_memo.remembered_read("svc", "me", reader) == "a"
    assert reader.calls == 2


def test_a_later_failure_drops_the_old_reading(keychain_file, monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(keychain_memo.time, "monotonic", lambda: clock[0])
    reader = _Reader(["a", None, "c"])
    keychain_memo.remembered_read("svc", "me", reader)
    clock[0] += keychain_memo.MAX_AGE_SECONDS + 1
    assert keychain_memo.remembered_read("svc", "me", reader) is None
    assert keychain_memo.remembered_read("svc", "me", reader) == "c"


def test_stat_failure_reads_every_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    keychain_memo.clear()
    reader = _Reader(["a", "b"])
    assert keychain_memo.remembered_read("svc", "me", reader) == "a"
    assert keychain_memo.remembered_read("svc", "me", reader) == "b"
    assert reader.calls == 2


def test_service_and_account_are_separate_keys(keychain_file) -> None:
    reader = _Reader(["a", "b"])
    assert keychain_memo.remembered_read("svc", "me", reader) == "a"
    assert keychain_memo.remembered_read("svc", None, reader) == "b"
