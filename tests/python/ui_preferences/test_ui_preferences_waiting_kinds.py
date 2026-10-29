
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bk_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bk_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, UiPreferencesStore

FIELD = "waiting_kinds"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    return path


@pytest.fixture
def store(config_path: Path) -> UiPreferencesStore:
    return UiPreferencesStore(lambda: config_path)


def _stored(config_path: Path) -> dict:
    return json.loads(config_path.read_text())["ui_preferences"]["values"]


def test_absent_stays_none(store, config_path):
    assert store.update({"theme": "matrix"}).status == COMMITTED
    assert FIELD not in _stored(config_path)
    assert ui_preferences.UiPreferenceValues().waiting_kinds is None


def test_round_trip_keeps_the_individual_switches_under_all_off(store, config_path):
    sent = {"v": 1, "all": False, "kinds": {"huddle": False, "alert_backup_health": False}}
    assert store.update({FIELD: sent}).status == COMMITTED
    assert _stored(config_path)[FIELD] == sent


def test_sparse_value_stores_only_what_was_sent(store, config_path):
    store.update({FIELD: {"v": 1, "kinds": {"automations": False}}})
    assert _stored(config_path)[FIELD] == {"v": 1, "kinds": {"automations": False}}


def test_null_returns_everything_to_on(store, config_path):
    store.update({FIELD: {"v": 1, "all": False}})
    store.update({FIELD: None})
    assert _stored(config_path).get(FIELD) is None


@pytest.mark.parametrize("bad_id", ["", "Approvals", "a b", "../x", "1abc", "x" * 65])
def test_kind_ids_are_spelling_checked(bad_id):
    with pytest.raises(ValueError):
        ui_preferences.validate_changes({FIELD: {"v": 1, "kinds": {bad_id: False}}})


@pytest.mark.parametrize("bad", [{"v": 1, "all": "no"}, {"v": 1, "kinds": {"huddle": 0}}, {"v": 2}, {"v": 1, "other": True}])
def test_only_booleans_and_known_keys_are_accepted(bad):
    with pytest.raises(ValueError):
        ui_preferences.validate_changes({FIELD: bad})


def test_too_many_kinds_are_refused():
    many = {f"alert_k{i}": False for i in range(65)}
    with pytest.raises(ValueError):
        ui_preferences.validate_changes({FIELD: {"v": 1, "kinds": many}})


def test_the_retired_bell_kinds_field_is_dropped_on_write():
    assert "bell_kinds" in ui_preferences.RETIRED_FIELDS
    assert "bell_kinds" not in ui_preferences.known_fields()
