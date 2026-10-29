
from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Iterator

import pytest

from src.core import config_writer
from src.core.read_caches.config_stat import CONFIG_READS

N = 20


@pytest.fixture
def config_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "provider_accounts": {"accounts": [{"id": "a1", "provider": "claude", "name": "One", "claude_config_dir": str(tmp_path / "c1")}]},
        "pack_machines": {"relay_consent": {"mode": "all"}},
    }))
    CONFIG_READS.clear()
    yield path
    CONFIG_READS.clear()


def config_opens(monkeypatch, path: Path) -> list:
    opened: list = []
    real = builtins.open

    def counting(file, *args, **kwargs):
        if str(file) == str(path):
            opened.append(str(file))
        return real(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting)
    monkeypatch.setattr(Path, "read_text", _counting_read_text(opened, path))
    return opened


def _counting_read_text(opened: list, path: Path):
    real = Path.read_text

    def counting(self, *args, **kwargs):
        if str(self) == str(path):
            opened.append(str(self))
        return real(self, *args, **kwargs)

    return counting


def test_accounts_list_reads_the_file_once_per_change(config_path, monkeypatch):
    from src.core.provider_ledger import accounts_store

    opened = config_opens(monkeypatch, config_path)
    for _ in range(N):
        assert [a.id for a in accounts_store.list_accounts(config_path)] == ["a1"]
    assert len(opened) == 1
    first = accounts_store.list_accounts(config_path)
    first[0].name = "edited"
    first.clear()
    assert accounts_store.list_accounts(config_path)[0].name == "One"

    def drop(doc: dict) -> dict:
        doc["provider_accounts"] = {"accounts": []}
        return doc

    config_writer.commit(config_path, drop)
    assert accounts_store.list_accounts(config_path) == []
    swap = config_path.with_name("swap.json")
    swap.write_text(json.dumps({"provider_accounts": {"accounts": [{"id": "a2", "provider": "claude", "name": "Two", "claude_config_dir": "/x"}]}}))
    swap.replace(config_path)
    assert [a.id for a in accounts_store.list_accounts(config_path)] == ["a2"]
    config_path.write_text(json.dumps({"provider_accounts": {"accounts": []}}))
    assert accounts_store.list_accounts(config_path) == []


def test_accounts_list_still_raises_for_a_missing_or_broken_file(config_path):
    from src.core.provider_ledger import accounts_store

    good = config_path.read_text()
    config_path.write_text("{ not json")
    with pytest.raises(ValueError):
        accounts_store.list_accounts(config_path)
    config_path.write_text(good)
    assert len(accounts_store.list_accounts(config_path)) == 1
    config_path.unlink()
    with pytest.raises(FileNotFoundError):
        accounts_store.list_accounts(config_path)


def test_pack_block_reads_the_file_once_per_change(config_path, monkeypatch):
    from src.core.pack.machines.config_state import ConfigState

    state = ConfigState(lambda: config_path)
    opened = config_opens(monkeypatch, config_path)
    for _ in range(N):
        assert state._block()["relay_consent"] == {"mode": "all"}
    assert len(opened) == 1
    state._block()["relay_consent"]["mode"] = "edited"
    assert state._block()["relay_consent"] == {"mode": "all"}
    assert state._commit("reserve", {"x": 1})
    assert state._block()["reserve"] == {"x": 1}


def test_a_same_size_in_place_edit_with_the_old_mtime_restored_is_still_seen(config_path):
    import os

    from src.core.provider_ledger import accounts_store

    assert [a.id for a in accounts_store.list_accounts(config_path)] == ["a1"]
    before = config_path.stat()
    text = config_path.read_text()
    config_path.write_text(text.replace('"a1"', '"b2"'))
    os.utime(config_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = config_path.stat()
    assert (after.st_mtime_ns, after.st_size, after.st_ino) == (before.st_mtime_ns, before.st_size, before.st_ino)
    assert [a.id for a in accounts_store.list_accounts(config_path)] == ["b2"]
