
from __future__ import annotations

import sqlite3

from src.api import catalog_installed_support as support
from src.core.skill_watch.store import DriftRecord, SkillWatchStore


def _seed(store: SkillWatchStore, install_id: str) -> None:
    store.save_baseline(install_id, "d", [("a", "644", "x"), ("b", "644", "y")])
    store.save_drift(DriftRecord(install_id, 1.0, "d", "clean", None))


def test_forget_removes_only_that_installs_rows(tmp_path):
    store = SkillWatchStore(tmp_path / "w.db")
    _seed(store, "gone")
    _seed(store, "kept")
    assert store.forget("gone") == 3
    assert store.baseline("gone", "d") is None and store.drift("gone") is None
    assert store.baseline("kept", "d") and store.drift("kept")


def test_forget_never_creates_the_file(tmp_path):
    store = SkillWatchStore(tmp_path / "none.db")
    assert store.forget("x") == 0
    assert not (tmp_path / "none.db").exists()


def test_uninstall_helper_forgets_and_survives_a_sqlite_error(tmp_path, monkeypatch):
    store = SkillWatchStore(tmp_path / "w.db")
    _seed(store, "i1")
    monkeypatch.setattr(support, "default_watch_store", lambda: store)
    support.forget_watch_rows("i1")
    assert store.drift("i1") is None

    class Broken:
        def forget(self, _id: str) -> int:
            raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(support, "default_watch_store", lambda: Broken())
    support.forget_watch_rows("i1")
