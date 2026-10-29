
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_stc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_stc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, UiPreferencesStore

FIELD = "sidebar_tab_colors"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    return path


@pytest.fixture
def store(config_path: Path) -> UiPreferencesStore:
    return UiPreferencesStore(lambda: config_path)


def test_absent_stays_none(store, config_path):
    assert store.update({"theme": "matrix"}).status == COMMITTED
    stored = json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert FIELD not in stored
    assert ui_preferences.UiPreferenceValues().sidebar_tab_colors is None


def test_round_trip(store, config_path):
    sent = {"agents": "green", "huddle": "violet"}
    assert store.update({FIELD: sent}).status == COMMITTED
    stored = json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert stored[FIELD] == sent


def test_null_returns_every_tab_to_default(store, config_path):
    store.update({FIELD: {"agents": "green"}})
    store.update({FIELD: None})
    stored = json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert stored.get(FIELD) is None


@pytest.mark.parametrize("bad", ["#ff0000", "red", "default", "", "ORANGE"])
def test_only_theme_colour_names_are_accepted(bad):
    with pytest.raises(ValueError):
        ui_preferences.validate_changes({FIELD: {"agents": bad}})


@pytest.mark.parametrize("bad_id", ["", "Agents", "a b", "../x", "x" * 65])
def test_tab_ids_are_spelling_checked(bad_id):
    with pytest.raises(ValueError):
        ui_preferences.validate_changes({FIELD: {bad_id: "green"}})


def test_every_colour_name_is_accepted():
    for name in ui_preferences.SIDEBAR_TAB_COLOR_NAMES:
        assert ui_preferences.validate_changes({FIELD: {"menu": name}}) == {FIELD: {"menu": name}}
