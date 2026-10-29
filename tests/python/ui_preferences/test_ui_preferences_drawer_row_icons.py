
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_dri_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_dri_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, UiPreferencesStore

FIELD = "drawer_row_icons"


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
    assert ui_preferences.UiPreferenceValues().drawer_row_icons is None


def test_a_full_block_commits_and_reads_back(store):
    value = {
        "compact": {
            "agents": True, "shells": False, "timers": False,
            "cup": False, "pin": False, "menu": False,
        },
        "cozy": {
            "agents": True, "shells": True, "timers": True,
            "cup": True, "pin": True, "menu": True,
        },
        "detailed": None,
    }
    result = store.update({FIELD: value})
    assert result.status == COMMITTED, result.detail
    expected = {
        density: ({**block, "context": None, "automations": None} if block else None)
        for density, block in value.items()
    }
    assert result.values[FIELD] == expected


def test_a_partial_density_only_sets_the_keys_given(store):
    result = store.update({FIELD: {"compact": {"agents": True}}})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == {
        "compact": {
            "agents": True, "shells": None, "timers": None,
            "cup": None, "pin": None, "menu": None, "context": None, "automations": None,
        },
        "cozy": None,
        "detailed": None,
    }


def test_hiding_just_the_kebab_does_not_touch_the_other_two_extras(store):
    result = store.update({FIELD: {"compact": {"menu": False}}})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["compact"] == {
        "agents": None, "shells": None, "timers": None,
        "cup": None, "pin": None, "menu": False, "context": None, "automations": None,
    }


def test_an_unknown_key_is_refused():
    with pytest.raises(Exception):
        ui_preferences.DrawerRowIconSet(agents=True, bogus=True)  # type: ignore[call-arg]


def test_defaults_table_is_compact_off_cozy_detailed_on():
    table = ui_preferences.drawer_row_icons_defaults()
    assert table["compact"] == {
        "agents": False, "shells": False, "timers": False,
        "cup": True, "pin": True, "menu": True, "context": True, "automations": True,
    }
    assert table["cozy"] == {
        "agents": True, "shells": True, "timers": True,
        "cup": True, "pin": True, "menu": True, "context": True, "automations": True,
    }
    assert table["detailed"] == {
        "agents": True, "shells": True, "timers": True,
        "cup": True, "pin": True, "menu": True, "context": True, "automations": True,
    }


def test_the_three_extra_toggles_default_shown_at_every_density():
    table = ui_preferences.drawer_row_icons_defaults()
    for density in ("compact", "cozy", "detailed"):
        for key in ("cup", "pin", "menu"):
            assert table[density][key] is True, f"{density}.{key} should default True"


def test_green_update_icon_has_no_field_here():
    fields = set(ui_preferences.DrawerRowIconSet.model_fields)
    assert fields == {"agents", "shells", "timers", "cup", "pin", "menu", "context", "automations"}


def test_context_gauge_defaults_on_at_every_density():
    table = ui_preferences.drawer_row_icons_defaults()
    for density in ("compact", "cozy", "detailed"):
        assert table[density]["context"] is True


def test_automations_icon_defaults_on_and_a_stored_value_is_sparse(store):
    table = ui_preferences.drawer_row_icons_defaults()
    for density in ("compact", "cozy", "detailed"):
        assert table[density]["automations"] is True
    result = store.update({FIELD: {"cozy": {"automations": True}}})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["cozy"]["automations"] is True
    assert result.values[FIELD]["cozy"]["agents"] is None
