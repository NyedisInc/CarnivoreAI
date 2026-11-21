
from __future__ import annotations

import json

import pytest

from src.core.pack.machines import config_state
from src.core.pack.reserve import model as reserve_model


def _state(tmp_path, doc):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(doc))
    return config_state.ConfigState(lambda: path), path


def test_it_runs_once_marks_the_block_and_keeps_the_owners_other_values(tmp_path):
    stored = reserve_model.ReserveConfig()
    stored.keyboard_rule.enabled = False
    stored.in_use.cpu_pct = 55
    state, path = _state(tmp_path, {"pack_machines": {"reserve": stored.model_dump()}, "other": 1})
    assert state.reserve().keyboard_rule.enabled is False
    assert state.migrate_keyboard_rule() is True
    doc = json.loads(path.read_text())
    assert doc["pack_machines"]["keyboard_rule_migrated"] is True and doc["other"] == 1
    assert doc["pack_machines"]["reserve"]["keyboard_rule"]["enabled"] is True and doc["pack_machines"]["reserve"]["in_use"]["cpu_pct"] == 55
    assert state.migrate_keyboard_rule() is False


def test_an_owners_later_off_survives_every_restart(tmp_path):
    state, path = _state(tmp_path, {})
    assert state.migrate_keyboard_rule() is True
    assert json.loads(path.read_text())["pack_machines"]["reserve"]["keyboard_rule"]["enabled"] is True, "an absent reserve is written, not left to the default"
    owner = state.reserve()
    owner.keyboard_rule.enabled = False
    state.save_reserve(owner)
    for _ in range(3):
        assert config_state.ConfigState(lambda: path).migrate_keyboard_rule() is False
    assert config_state.ConfigState(lambda: path).reserve().keyboard_rule.enabled is False


def test_a_stored_reserve_that_does_not_parse_is_kept_and_only_the_marker_is_written(tmp_path):
    odd = {"in_use": {"cpu_pct": 95}, "from_a_newer_build": 1}
    state, path = _state(tmp_path, {"pack_machines": {"reserve": odd}})
    assert state.migrate_keyboard_rule() is True
    block = json.loads(path.read_text())["pack_machines"]
    assert block["reserve"] == odd and block["keyboard_rule_migrated"] is True


def test_a_missing_or_unreadable_file_raises_so_boot_logs_it_and_retries(tmp_path):
    absent = tmp_path / "absent" / "config.json"
    with pytest.raises(OSError):
        config_state.ConfigState(lambda: absent).migrate_keyboard_rule()
    assert not absent.exists()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises((OSError, ValueError)):
        config_state.ConfigState(lambda: bad).migrate_keyboard_rule()
    assert bad.read_text() == "{not json"
