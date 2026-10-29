from __future__ import annotations

import os
import time

import pytest

from src.core.attention import registry_index
from src.core.stat_gate import dir_names
from src.core.subagents import reader


@pytest.fixture
def scans(monkeypatch):
    dir_names.clear()
    calls = []
    real = os.scandir
    monkeypatch.setattr(dir_names.os, "scandir", lambda p: calls.append(p) or real(p))
    return calls


def _age(path, seconds=60):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_listing_remembered_and_redone_after_add(tmp_path, scans):
    (tmp_path / "a.json").write_text("{}")
    _age(tmp_path)
    for _ in range(4):
        assert dir_names.entry_names(tmp_path) == ("a.json",)
    assert len(scans) == 1
    (tmp_path / "b.json").write_text("{}")
    assert dir_names.entry_names(tmp_path) == ("a.json", "b.json")
    assert len(scans) == 2


def test_recently_changed_folder_is_not_trusted(tmp_path, scans):
    (tmp_path / "a.json").write_text("{}")
    dir_names.entry_names(tmp_path)
    dir_names.entry_names(tmp_path)
    assert len(scans) == 2


def test_missing_folder_raises_like_scandir(tmp_path):
    with pytest.raises(OSError):
        dir_names.entry_names(tmp_path / "nope")


def test_subagent_scan_sees_a_new_agent_and_an_appended_file(tmp_path, scans):
    folder = tmp_path / "subagents"
    folder.mkdir()
    first = folder / "agent-aaa1111111111111a.jsonl"
    first.write_text("{}\n")
    os.utime(first, (1000, 1000))
    _age(folder)
    got, _ = reader._scan(folder)
    again, _ = reader._scan(folder)
    assert len(scans) == 1 and [c.mtime for c in again] == [c.mtime for c in got] == [1000.0]
    os.utime(first, (2000, 2000))
    assert [c.mtime for c in reader._scan(folder)[0]] == [2000.0]
    assert len(scans) == 1
    second = folder / "agent-bbb2222222222222b.jsonl"
    second.write_text("{}\n")
    assert len(reader._scan(folder)[0]) == 2


def test_registry_index_sees_new_and_rewritten_records(tmp_path, scans):
    (tmp_path / "1.json").write_text("{}")
    _age(tmp_path)
    registry_index.read_registry_index(str(tmp_path))
    registry_index.read_registry_index(str(tmp_path))
    assert len(scans) == 1
    (tmp_path / "2.json").write_text("{}")
    registry_index.read_registry_index(str(tmp_path))
    assert len(scans) == 2
