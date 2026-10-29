from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.agent_wrappers import AgentWrapper
from tests.helpers.wrapper_seeds import without_standard_seeds
from src.core.config_migration import (
    CURRENT_CONFIG_VERSION,
    _step_v2_to_v3,
    migrate_config_dict,
)


def _live_v2_config() -> dict:
    return {
        "config_version": 2,
        "agents": {
            "claude_command": "claude --dangerously-skip-permissions",
            "codex_command": "codex",
            "hermes_command": "hermes",
            "openclaw_command": "openclaw tui",
            "wrappers": [
                {
                    "id": "claude-skip-permissions",
                    "label": "claude",
                    "script": "claude --dangerously-skip-permissions",
                    "entry": None,
                    "description": "Plain claude launch.",
                    "default": True,
                    "accepts_model": False,
                },
                {
                    "id": "keyc",
                    "label": "keyc (keychain-backed)",
                    "script": "keyc() (\n  command claude\n)",
                    "entry": "keyc",
                    "description": "the team keyc, verbatim.",
                    "default": False,
                    "accepts_model": False,
                },
            ],
        },
        "terminal_commands": [{"id": "mine", "label": "mine", "command": "ls"}],
    }



def test_v2_to_v3_stamps_family_claude_on_every_existing_wrapper():
    new_data, changed = migrate_config_dict(_live_v2_config(), True, True)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION
    assert [w["family"] for w in without_standard_seeds(new_data["agents"]["wrappers"])] == ["claude", "claude"]


def test_v2_to_v3_never_changes_a_wrapper_id():
    after, _ = migrate_config_dict(_live_v2_config(), True, True)
    assert [w["id"] for w in without_standard_seeds(after["agents"]["wrappers"])] == [
        "claude-skip-permissions",
        "keyc",
    ]


def test_v2_to_v3_preserves_every_other_wrapper_field_verbatim():
    before = _live_v2_config()
    after = _step_v2_to_v3(before)
    for old, new in zip(before["agents"]["wrappers"], without_standard_seeds(after["agents"]["wrappers"])):
        for key, value in old.items():
            assert new[key] == value, key
        assert set(new) - set(old) == {"family"}


def test_v2_to_v3_preserves_the_default_flag_and_which_wrapper_holds_it():
    after, _ = migrate_config_dict(_live_v2_config(), True, True)
    by_id = {w["id"]: w for w in without_standard_seeds(after["agents"]["wrappers"])}
    assert by_id["claude-skip-permissions"]["default"] is True
    assert by_id["keyc"]["default"] is False


def test_v2_to_v3_keeps_every_legacy_command_key():
    after, _ = migrate_config_dict(_live_v2_config(), True, True)
    agents = after["agents"]
    assert agents["claude_command"] == "claude --dangerously-skip-permissions"
    assert agents["codex_command"] == "codex"
    assert agents["hermes_command"] == "hermes"
    assert agents["openclaw_command"] == "openclaw tui"


def test_v2_to_v3_never_mutates_its_input():
    before = _live_v2_config()
    migrate_config_dict(before, True, True)
    assert "family" not in before["agents"]["wrappers"][0]



def test_v2_to_v3_does_not_clobber_a_user_edited_family():
    data = _live_v2_config()
    data["agents"]["wrappers"][1]["family"] = "codex"
    after, _ = migrate_config_dict(data, True, True)
    assert without_standard_seeds(after["agents"]["wrappers"])[1]["family"] == "codex"


def test_v2_to_v3_does_not_clobber_user_edited_terminal_commands():
    after, _ = migrate_config_dict(_live_v2_config(), True, True)
    assert after["terminal_commands"] == [{"id": "mine", "label": "mine", "command": "ls"}]


def test_v2_to_v3_does_not_clobber_a_user_edited_claude_command():
    data = _live_v2_config()
    data["agents"]["claude_command"] = "my --own --thing"
    after, _ = migrate_config_dict(data, True, True)
    assert after["agents"]["claude_command"] == "my --own --thing"



def test_v2_to_v3_step_is_idempotent_on_its_own():
    once = _step_v2_to_v3(_live_v2_config())
    twice = _step_v2_to_v3(once)
    assert twice == once


def test_migration_from_v2_is_idempotent_end_to_end():
    first, changed1 = migrate_config_dict(_live_v2_config(), True, True)
    assert changed1 is True
    second, changed2 = migrate_config_dict(first, True, True)
    assert changed2 is False
    assert second == first


def test_a_config_already_at_the_current_version_is_a_complete_noop():
    data = _live_v2_config()
    data["config_version"] = CURRENT_CONFIG_VERSION
    for w in data["agents"]["wrappers"]:
        w["family"] = "claude"
    new_data, changed = migrate_config_dict(data, True, True)
    assert changed is False
    assert new_data is data



def test_v2_config_with_no_wrappers_at_all_still_reaches_v3():
    data = {"config_version": 2, "agents": {"claude_command": "claude --foo"}}
    new_data, changed = migrate_config_dict(data, True, True)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION
    assert new_data["agents"]["claude_command"] == "claude --foo"


def test_v2_config_with_an_empty_wrapper_list_reaches_v3():
    data = {"config_version": 2, "agents": {"wrappers": []}}
    new_data, changed = migrate_config_dict(data, True, True)
    assert changed is True
    assert without_standard_seeds(new_data["agents"]["wrappers"]) == []


def test_v2_to_v3_tolerates_a_malformed_wrapper_entry():
    data = {"config_version": 2, "agents": {"wrappers": ["not-a-dict"]}}
    new_data, changed = migrate_config_dict(data, True, True)
    assert changed is True
    assert without_standard_seeds(new_data["agents"]["wrappers"]) == ["not-a-dict"]


def test_v2_to_v3_tolerates_a_non_list_wrappers_value():
    data = {"config_version": 2, "agents": {"wrappers": "nonsense"}}
    new_data, changed = migrate_config_dict(data, True, True)
    assert changed is True
    assert new_data["agents"]["wrappers"] == "nonsense"


def test_v2_to_v3_tolerates_a_missing_agents_block():
    data = {"config_version": 2, "projects": []}
    new_data, changed = migrate_config_dict(data, True, True)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION



@pytest.mark.parametrize("start_version", [0, 1, 2, 3])
def test_every_starting_version_ends_up_current_with_families(start_version):
    data = _live_v2_config()
    if start_version == 0:
        del data["config_version"]
    else:
        data["config_version"] = start_version
    if start_version == 3:
        for w in data["agents"]["wrappers"]:
            w["family"] = "claude"

    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is (start_version < CURRENT_CONFIG_VERSION)
    assert new_data["config_version"] >= CURRENT_CONFIG_VERSION
    for w in without_standard_seeds(new_data["agents"]["wrappers"]):
        assert w["family"] == "claude"
    assert [w["id"] for w in without_standard_seeds(new_data["agents"]["wrappers"])] == [
        "claude-skip-permissions",
        "keyc",
    ]


@pytest.mark.parametrize("start_version", [0, 1, 2, 3])
def test_migrated_wrappers_validate_against_the_model(start_version):
    data = _live_v2_config()
    if start_version == 0:
        del data["config_version"]
    else:
        data["config_version"] = start_version
    if start_version == 3:
        for w in data["agents"]["wrappers"]:
            w["family"] = "claude"

    new_data, _ = migrate_config_dict(data, True, True)
    for raw in without_standard_seeds(new_data["agents"]["wrappers"]):
        assert AgentWrapper(**raw).family == "claude"


@pytest.mark.parametrize("start_version", [0, 1, 2])
def test_a_config_with_no_wrappers_works_from_every_version(start_version):
    data = {"agents": {"claude_command": "claude --x"}}
    if start_version:
        data["config_version"] = start_version
    new_data, changed = migrate_config_dict(data, has_cld=False, has_cldor=False)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION
