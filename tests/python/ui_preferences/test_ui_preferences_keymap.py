
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_km_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_km_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, UiPreferencesStore

FIELD = "keymap"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    return path


@pytest.fixture
def store(config_path: Path) -> UiPreferencesStore:
    return UiPreferencesStore(lambda: config_path)


def _stored(path: Path) -> dict[str, object]:
    return json.loads(path.read_text()).get("ui_preferences", {}).get("values", {})


def test_absent_stays_none(store: UiPreferencesStore, config_path: Path) -> None:
    assert store.update({"theme": "matrix"}).status == COMMITTED
    assert FIELD not in _stored(config_path)
    assert ui_preferences.UiPreferenceValues().keymap is None


def test_a_valid_override_round_trips(store: UiPreferencesStore, config_path: Path) -> None:
    value = {"mac": {"history.back": ["shift+cmd+arrowleft"], "palette.actions": []}, "other": {"history.back": ["ctrl+shift+arrowleft"]},
             "mouse": {"mouse.tab.close": ["middle"]}}
    assert store.update({FIELD: value}).status == COMMITTED
    assert _stored(config_path)[FIELD] == value


@pytest.mark.parametrize("family, chord", [
    ("mac", "ctrl+c"),
    ("mac", "cmd+q"),
    ("other", "ctrl+c"),
    ("other", "alt+b"),
    ("other", "ctrl+shift+t"),
    ("other", "ctrl+shift+c"),
    ("other", "ctrl+shift+v"),
    ("mac", "cmd+f"),
    ("other", "ctrl+alt+j"),
    ("mac", "escape"), ("mac", "tab"), ("mac", "Cmd+J"), ("mac", "cmd+shift+j"),
])
def test_a_protected_or_malformed_chord_is_refused_by_the_server(store: UiPreferencesStore, config_path: Path, family: str, chord: str) -> None:
    result = store.update({FIELD: {family: {"history.back": [chord]}}})
    assert result.status == REJECTED_INVALID
    assert f"'{chord}'" not in (result.detail or "") and f'"{chord}"' not in (result.detail or "")
    assert FIELD not in _stored(config_path)


def test_a_menu_letter_may_be_a_bare_key_but_never_escape(store: UiPreferencesStore) -> None:
    assert store.update({FIELD: {"mac": {"menu.rename": ["e"]}}}).status == COMMITTED
    assert store.update({FIELD: {"mac": {"menu.rename": ["escape"]}}}).status == REJECTED_INVALID


@pytest.mark.parametrize("bad", [
    {"windows": {}}, {"mac": []}, {"mac": {"History Back": ["cmd+j"]}}, {"mac": {"history.back": ["cmd+j", "cmd+j"]}},
    {"mac": {"history.back": ["cmd+j", "cmd+k", "cmd+l", "cmd+o", "cmd+p"]}}, {"mouse": {"mouse.tab.close": ["double"]}},
])
def test_a_badly_shaped_block_is_refused(store: UiPreferencesStore, bad: dict[str, object]) -> None:
    assert store.update({FIELD: bad}).status == REJECTED_INVALID


@pytest.mark.parametrize("action_id, chord", [("form.submit", "j"), ("palette.next", "y"), ("terminal.search.next", "n")])
def test_an_action_in_a_text_box_needs_a_modifier(store: UiPreferencesStore, config_path: Path, action_id: str, chord: str) -> None:
    result = store.update({FIELD: {"mac": {action_id: [chord]}}})
    assert result.status == REJECTED_INVALID
    assert FIELD not in _stored(config_path)
    assert store.update({FIELD: {"mac": {action_id: ["cmd+" + chord]}}}).status == COMMITTED
