
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.core import ui_preferences
from src.core.deepsearch import index_scope, scope_migration as migration
from src.core.ui_preferences_store import UiPreferencesStore
from src.cplugs.host import state as owner_state


def _state(state_dir: Path, entries: Dict[str, Any]) -> None:
    path = owner_state.state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": owner_state.STATE_VERSION, "cplugs": entries}))


def _store(tmp_path: Path) -> UiPreferencesStore:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"unrelated": 1}))
    return UiPreferencesStore(lambda: config)


def test_a_chosen_scope_carries_over_once_and_never_over_a_later_choice(tmp_path: Path) -> None:
    _state(tmp_path, {"deepsearch": {"enabled": True, "revision": 2, "settings": {"indexScope": "human+subsessions"}}})
    store = _store(tmp_path)
    assert migration.migrate(tmp_path, store) is True
    assert store.read()["values"] == {"deepsearch_index_scope": "human+subsessions"}
    store.update({"deepsearch_index_scope": "human"})
    assert migration.migrate(tmp_path, store) is False
    assert store.read()["values"]["deepsearch_index_scope"] == "human"
    assert owner_state.stored_entry(tmp_path, "deepsearch") is not None


def test_nothing_to_carry_writes_nothing_and_the_default_reads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert migration.migrate(tmp_path, store) is False
    for settings in ({}, {"indexScope": "everything"}, {"indexScope": 3}):
        _state(tmp_path, {"deepsearch": {"enabled": True, "revision": 1, "settings": settings}})
        assert migration.migrate(tmp_path, store) is False, settings
    assert store.read()["values"] == {}
    index_scope.install(store.read)
    try:
        assert index_scope.current() == "all"
    finally:
        index_scope.uninstall()


def test_a_missing_config_is_logged_and_retried_not_raised(tmp_path: Path) -> None:
    _state(tmp_path, {"deepsearch": {"enabled": True, "revision": 1, "settings": {"indexScope": "human"}}})
    store = UiPreferencesStore(lambda: tmp_path / "no-config.json")
    assert migration.migrate(tmp_path, store) is False


def test_the_preference_accepts_only_the_three_scope_words(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for scope in ui_preferences.DEEPSEARCH_INDEX_SCOPES:
        assert store.update({"deepsearch_index_scope": scope}).status in ("committed", "unchanged")
    refused = store.update({"deepsearch_index_scope": "none"})
    assert refused.status == "rejected_invalid" and store.read()["values"]["deepsearch_index_scope"] == "all"
    assert store.update({"deepsearch_index_scope": None}).status == "committed"
    assert "deepsearch_index_scope" not in store.read()["values"]
