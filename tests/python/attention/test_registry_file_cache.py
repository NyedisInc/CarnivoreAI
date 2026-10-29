
from __future__ import annotations

import json
import os

from src.core.attention import registry_index
from src.core.attention import registry_record


def _write(directory, pid: int, status: str) -> None:
    (directory / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "sessionId": "u", "status": status, "tmux": "cloude_a:@1.%1",
        "statusUpdatedAt": 1, "startedAt": 1, "version": "2.1.286"}))


def test_unchanged_file_is_not_reread_but_a_rewrite_and_a_dead_pid_are_seen(tmp_path, monkeypatch):
    reads = []
    real = registry_index._load_registry_file
    alive = {"value": True}

    def loader(path, name):
        reads.append(name)
        return real(path, name)

    monkeypatch.setattr(registry_index, "_load_registry_file", loader)
    monkeypatch.setattr(registry_index, "pid_is_running", lambda pid: alive["value"])
    _write(tmp_path, 41, "idle")
    for _ in range(3):
        assert registry_index.read_registry_index(str(tmp_path))["cloude_a"].status == "idle"
    assert reads == ["41.json"]

    _write(tmp_path, 41, "busy")
    os.utime(tmp_path / "41.json", ns=(1, 2))
    assert registry_index.read_registry_index(str(tmp_path))["cloude_a"].status == "busy"
    assert reads == ["41.json", "41.json"]

    alive["value"] = False
    record = registry_index.read_registry_index(str(tmp_path))["cloude_a"]
    assert record.verdict == registry_record.REG_STALE
    assert reads == ["41.json", "41.json"]


def test_a_torn_read_is_never_kept(tmp_path, monkeypatch):
    reads = []
    real = registry_index._load_registry_file

    def loader(path, name):
        reads.append(name)
        return real(path, name)

    monkeypatch.setattr(registry_index, "_load_registry_file", loader)
    (tmp_path / "42.json").write_text('{"pid": 42, "sta')
    registry_index.read_registry_index(str(tmp_path))
    registry_index.read_registry_index(str(tmp_path))
    assert reads == ["42.json", "42.json"]
