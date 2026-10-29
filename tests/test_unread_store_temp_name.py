
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ustn_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ustn_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import unread_store as unread_store_module
from src.core.unread_store import UnreadStore

LEGACY_FIXED_NAME = "unread_state.json.tmp"


def _record_replaces(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    seen: List[str] = []
    real_replace = os.replace

    def _spy(src: Any, dst: Any) -> None:
        seen.append(str(src))
        real_replace(src, dst)

    monkeypatch.setattr(unread_store_module.os, "replace", _spy)
    return seen


def test_two_writes_use_two_distinct_temp_paths(tmp_path, monkeypatch):
    path = tmp_path / "unread_state.json"
    seen = _record_replaces(monkeypatch)
    store = UnreadStore(path)

    store.set_flag("cloude_a", "auto", True, epoch=5)
    store.set_flag("cloude_b", "auto", True, epoch=6)

    assert len(seen) == 2, "both writes must have gone through os.replace"
    assert len(set(seen)) == 2, (
        "two writes reused one temp filename; two writers streaming into "
        f"one file publish an interleaved document. Observed: {seen}"
    )


def test_no_write_uses_the_legacy_fixed_temp_name(tmp_path, monkeypatch):
    path = tmp_path / "unread_state.json"
    seen = _record_replaces(monkeypatch)
    store = UnreadStore(path)

    store.set_flag("cloude_a", "auto", True, epoch=5)
    store.clear("cloude_a", 5)

    assert seen, "the fixture recorded no write at all"
    for observed in seen:
        assert Path(observed).name != LEGACY_FIXED_NAME, (
            "the store is back on the shared fixed temp name"
        )


def test_two_stores_on_one_path_do_not_share_a_temp_name(tmp_path, monkeypatch):
    path = tmp_path / "unread_state.json"
    seen = _record_replaces(monkeypatch)

    UnreadStore(path).set_flag("cloude_a", "auto", True, epoch=5)
    UnreadStore(path).set_flag("cloude_b", "auto", True, epoch=6)

    assert len(set(seen)) == 2, f"two instances shared a temp path: {seen}"


def test_the_temp_file_is_a_sibling_of_the_target(tmp_path, monkeypatch):
    path = tmp_path / "unread_state.json"
    seen = _record_replaces(monkeypatch)
    UnreadStore(path).set_flag("cloude_a", "auto", True, epoch=5)

    assert Path(seen[0]).parent == path.parent


def test_the_written_file_is_valid_complete_json(tmp_path):
    path = tmp_path / "unread_state.json"
    store = UnreadStore(path)
    store.set_flag("cloude_a", "auto", True, epoch=5)
    store.set_flag("cloude_b", "manual", True, epoch=6)

    on_disk = json.loads(path.read_text())
    assert on_disk == {
        "cloude_a@5": {"auto": True, "manual": False},
        "cloude_b@6": {"auto": False, "manual": True},
    }

    reloaded = UnreadStore(path)
    assert reloaded.is_unread("cloude_a", 5) is True
    assert reloaded.is_unread("cloude_b", 6) is True


def test_a_successful_write_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "unread_state.json"
    store = UnreadStore(path)
    store.set_flag("cloude_a", "auto", True, epoch=5)
    store.set_flag("cloude_a", "manual", True, epoch=5)

    assert list(tmp_path.iterdir()) == [path]


def test_a_failed_write_leaves_no_orphan_temp_file(tmp_path):
    path = tmp_path / "unread_state.json"
    store = UnreadStore(path)
    store.set_flag("cloude_a", "auto", True, epoch=5)
    good_bytes = path.read_text()

    store.raw["cloude_bad"] = {"auto": object(), "manual": False}
    store._save()

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != path.name]
    assert leftovers == [], f"failed write left temp files behind: {leftovers}"
    assert path.read_text() == good_bytes, (
        "a failed write must leave the previous document untouched"
    )
