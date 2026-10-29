
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict

from src.core.crosstalk import card_prefs_migration as migration
from src.core.crosstalk import card_push
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


def test_an_install_with_the_plugin_on_keeps_its_cards_and_choices_and_it_runs_once(tmp_path: Path) -> None:
    _state(tmp_path, {"xtalk": {"enabled": True, "revision": 3, "settings": {"senderCards": False, "keepCards": True, "junk": 1}}})
    store = _store(tmp_path)
    assert migration.migrate(tmp_path, store) is True
    assert store.read()["values"] == {"crosstalk_cards": True, "crosstalk_card_sender": False, "crosstalk_card_keep": True}
    store.update({"crosstalk_cards": False})
    assert migration.migrate(tmp_path, store) is False
    assert store.read()["values"]["crosstalk_cards"] is False
    assert owner_state.stored_entry(tmp_path, "xtalk") is not None


def test_the_plugin_off_or_never_stored_migrates_to_off_and_marks_the_install(tmp_path: Path) -> None:
    _state(tmp_path, {"xtalk": {"enabled": False, "revision": 1, "settings": {"receiverCards": False}}})
    store = _store(tmp_path)
    assert migration.migrate(tmp_path, store) is True
    assert store.read()["values"]["crosstalk_cards"] is False
    fresh = _store(tmp_path / "fresh") if (tmp_path / "fresh").mkdir() is None else None
    assert migration.migrate(tmp_path / "fresh", fresh) is True
    assert fresh.read()["values"] == {"crosstalk_cards": False}


def test_the_card_push_follows_the_preference_the_migration_wrote(tmp_path: Path) -> None:
    _state(tmp_path, {"xtalk": {"enabled": True, "revision": 1, "settings": {}}})
    store = _store(tmp_path)
    frames: list = []
    loop = asyncio.new_event_loop()
    card_push.install(lambda frame: frames.append(frame) or 1, loop, store.read)
    try:
        card_push.announce({"id": "before", "text": "x"})
        loop.run_until_complete(asyncio.sleep(0))
        assert frames == []
        migration.migrate(tmp_path, store)
        card_push.announce({"id": "m-1", "text": "ping"})
        loop.run_until_complete(asyncio.sleep(0))
        assert [f["id"] for f in frames] == ["m-1"]
        store.update({"crosstalk_cards": False})
        card_push.announce({"id": "m-2", "text": "ping"})
        loop.run_until_complete(asyncio.sleep(0))
        assert [f["id"] for f in frames] == ["m-1"]
    finally:
        card_push.uninstall()
        loop.close()
