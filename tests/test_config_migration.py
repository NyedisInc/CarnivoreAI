from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from tests.helpers.wrapper_seeds import without_standard_seeds
from src.core.config_migration import (
    CURRENT_CONFIG_VERSION,
    _step_v1_to_v2,
    _step_v2_to_v3,
    build_seed_wrappers,
    ensure_config_migrated,
    migrate_config_dict,
    migrate_config_file,
    probe_shell_function,
)



def _fake_runner(returncode_map):
    def runner(argv):
        name = argv[-1].split()[-1]
        return subprocess.CompletedProcess(argv, returncode_map.get(name, 1))
    return runner


def test_probe_shell_function_found():
    runner = _fake_runner({"cld": 0})
    assert probe_shell_function("cld", runner=runner) is True


def test_probe_shell_function_not_found():
    runner = _fake_runner({"cld": 1})
    assert probe_shell_function("cld", runner=runner) is False


def test_probe_shell_function_runner_exception_is_not_found():
    def raising_runner(argv):
        raise OSError("zsh not found")
    assert probe_shell_function("cld", runner=raising_runner) is False



def test_build_seed_wrappers_neither_detected():
    wrappers = build_seed_wrappers(False, False)
    ids = [w["id"] for w in wrappers]
    assert ids == ["claude"]
    assert wrappers[0]["default"] is True


def test_build_seed_wrappers_cld_only():
    wrappers = build_seed_wrappers(True, False)
    ids = [w["id"] for w in wrappers]
    assert ids == ["claude", "cld"]
    by_id = {w["id"]: w for w in wrappers}
    assert by_id["cld"]["default"] is True
    assert by_id["claude"]["default"] is False


def test_build_seed_wrappers_both_detected():
    wrappers = build_seed_wrappers(True, True)
    ids = [w["id"] for w in wrappers]
    assert ids == ["claude", "cld", "cldor"]
    by_id = {w["id"]: w for w in wrappers}
    assert by_id["cld"]["default"] is True
    assert by_id["cldor"]["default"] is False



def test_migrate_old_keys_only_seeds_wrappers_and_stamps_version():
    data = {
        "agents": {
            "claude_command": "",
            "codex_command": "codex",
            "hermes_command": "hermes",
            "openclaw_command": "openclaw tui",
        }
    }
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION
    ids = [w["id"] for w in without_standard_seeds(new_data["agents"]["wrappers"])]
    assert ids == ["claude", "cld", "cldor"]
    assert new_data["agents"]["codex_command"] == "codex"
    assert new_data["agents"]["hermes_command"] == "hermes"
    assert new_data["agents"]["openclaw_command"] == "openclaw tui"
    assert new_data["agents"]["claude_command"] == ""
    assert "wrappers" not in data["agents"]
    assert "config_version" not in data


def test_migrate_no_agents_block_at_all():
    data = {"projects": []}
    new_data, changed = migrate_config_dict(data, has_cld=False, has_cldor=False)
    assert changed is True
    assert new_data["agents"]["wrappers"][0]["id"] == "claude"
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION


def test_migrate_neither_cld_nor_cldor_detected_seeds_plain_claude_only():
    data = {"agents": {}}
    new_data, changed = migrate_config_dict(data, has_cld=False, has_cldor=False)
    assert changed is True
    ids = [w["id"] for w in without_standard_seeds(new_data["agents"]["wrappers"])]
    assert ids == ["claude"]



def test_migration_idempotent_second_run_is_noop():
    data = {"agents": {}}
    first, changed1 = migrate_config_dict(data, has_cld=True, has_cldor=False)
    assert changed1 is True
    second, changed2 = migrate_config_dict(first, has_cld=True, has_cldor=False)
    assert changed2 is False
    assert second == first


def test_already_current_version_untouched_even_with_different_probe_results():
    data = {"config_version": CURRENT_CONFIG_VERSION, "agents": {"wrappers": [{"id": "cld"}]}}
    new_data, changed = migrate_config_dict(data, has_cld=False, has_cldor=False)
    assert changed is False
    assert new_data is data



def test_malformed_agents_block_leaves_config_untouched():
    data = {"agents": "not-a-dict", "config_version": 0}
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is False
    assert new_data is data
    assert "config_version" not in new_data or new_data["config_version"] == 0


def test_bad_version_type_leaves_config_untouched():
    data = {"config_version": "not-an-int", "agents": {}}
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is False
    assert new_data is data


def test_explicit_claude_command_present_seeds_no_cld_and_folds_the_command():
    data = {"agents": {"claude_command": "claude --dangerously-skip-permissions"}}
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION
    claude = [w for w in new_data["agents"]["wrappers"] if w["family"] == "claude"]
    assert [(w["id"], w["script"], w["default"]) for w in claude] == [
        ("claude", 'claude --dangerously-skip-permissions "$@"', True),
    ]
    assert new_data["agents"]["claude_command"] == "claude --dangerously-skip-permissions"


def test_existing_wrappers_block_not_overwritten():
    data = {"agents": {"wrappers": [{"id": "custom", "label": "x", "script": "y", "default": True}]}}
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is True
    assert without_standard_seeds(new_data["agents"]["wrappers"]) == [
        {
            "id": "custom",
            "label": "x",
            "script": "y",
            "default": True,
            "accepts_model": False,
            "family": "claude",
        }
    ]
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION



def test_migrate_config_file_writes_backup_and_migrates(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    original = {"agents": {"codex_command": "codex"}}
    config_path.write_text(json.dumps(original, indent=2))

    monkeypatch.setattr(
        "src.core.config_migration.probe_shell_function",
        lambda name, runner=None: name == "cld",
    )

    result = migrate_config_file(config_path)
    assert result["migrated"] is True
    assert result["wrapper_ids"][:2] == ["claude", "cld"]

    backup_path = config_path.with_suffix(".json.bak")
    assert backup_path.exists()
    assert json.loads(backup_path.read_text()) == original

    on_disk = json.loads(config_path.read_text())
    assert on_disk["config_version"] == CURRENT_CONFIG_VERSION
    assert [w["id"] for w in without_standard_seeds(on_disk["agents"]["wrappers"])] == ["claude", "cld"]
    assert on_disk["agents"]["codex_command"] == "codex"

    tmp_file = config_path.with_suffix(".json.tmp")
    assert not tmp_file.exists()


def test_migrate_config_file_noop_leaves_no_backup(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    already_current = {"config_version": CURRENT_CONFIG_VERSION, "agents": {"wrappers": []}}
    config_path.write_text(json.dumps(already_current, indent=2))

    calls = _counting_probe(monkeypatch)

    result = migrate_config_file(config_path)
    assert result["migrated"] is False
    assert calls == [], f"a no-op migration probed the shell: {calls}"

    backup_path = config_path.with_suffix(".json.bak")
    assert not backup_path.exists()
    assert json.loads(config_path.read_text()) == already_current


def test_migrate_config_file_missing_raises():
    with pytest.raises(FileNotFoundError):
        migrate_config_file(Path("/nonexistent/config.json"))


def test_migrate_config_file_invalid_json_raises(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{not valid json")
    with pytest.raises(ValueError):
        migrate_config_file(config_path)


def test_ensure_config_migrated_never_raises_on_missing_file(tmp_path):
    ensure_config_migrated(tmp_path / "nope.json")


def test_ensure_config_migrated_never_raises_on_invalid_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{bad")
    ensure_config_migrated(config_path)



def _v1_config_with_wrappers():
    return {
        "config_version": 1,
        "agents": {
            "claude_command": "",
            "codex_command": "codex",
            "wrappers": [
                {"id": "claude", "label": "claude", "script": "claude", "default": False},
                {
                    "id": "cld",
                    "label": "cld (subscription)",
                    "script": 'cld "$@"',
                    "description": "subscription OAuth via macOS Keychain",
                    "default": True,
                },
                {
                    "id": "cldor",
                    "label": "cldor (openrouter)",
                    "script": 'cldor "$@"',
                    "description": "OpenRouter-routed, model as first argument",
                    "default": False,
                },
            ],
        },
    }


def test_v1_with_wrappers_gains_accepts_model():
    data = _v1_config_with_wrappers()
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION

    by_id = {w["id"]: w for w in new_data["agents"]["wrappers"]}
    assert [w["id"] for w in without_standard_seeds(new_data["agents"]["wrappers"])] == ["claude", "cld", "cldor"]
    assert by_id["cldor"]["accepts_model"] is True
    assert by_id["cld"]["accepts_model"] is False
    assert by_id["claude"]["accepts_model"] is False
    assert by_id["cld"]["default"] is True
    assert by_id["cld"]["script"] == 'cld "$@"'
    assert new_data["agents"]["codex_command"] == "codex"
    assert new_data["agents"]["claude_command"] == ""
    assert "accepts_model" not in data["agents"]["wrappers"][2]


def test_v1_without_wrappers_still_works():
    data = {"config_version": 1, "agents": {"claude_command": "claude --foo"}}
    new_data, changed = migrate_config_dict(data, has_cld=False, has_cldor=False)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION
    folded = [w for w in new_data["agents"]["wrappers"] if w["family"] == "claude"]
    assert [w["script"] for w in folded] == ['claude --foo "$@"']
    assert new_data["agents"]["claude_command"] == "claude --foo"


def test_v1_with_no_agents_block_at_all():
    data = {"config_version": 1, "projects": []}
    new_data, changed = migrate_config_dict(data, has_cld=False, has_cldor=False)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION


def test_v0_runs_both_steps():
    data = {"agents": {"codex_command": "codex"}}
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is True
    assert new_data["config_version"] == CURRENT_CONFIG_VERSION
    by_id = {w["id"]: w for w in without_standard_seeds(new_data["agents"]["wrappers"])}
    assert set(by_id) == {"claude", "cld", "cldor"}
    assert by_id["cldor"]["accepts_model"] is True
    assert by_id["cld"]["accepts_model"] is False


def test_already_current_is_a_complete_noop():
    data = {
        "config_version": CURRENT_CONFIG_VERSION,
        "agents": {"wrappers": [{"id": "cld", "label": "cld", "script": "x", "accepts_model": True}]},
    }
    new_data, changed = migrate_config_dict(data, has_cld=True, has_cldor=True)
    assert changed is False
    assert new_data is data


def test_v2_does_not_overwrite_an_explicit_accepts_model():
    data = {
        "config_version": 1,
        "agents": {
            "wrappers": [
                {"id": "w", "label": "openrouter thing", "script": "x", "accepts_model": False}
            ]
        },
    }
    new_data, _ = migrate_config_dict(data, has_cld=False, has_cldor=False)
    assert new_data["agents"]["wrappers"][0]["accepts_model"] is False


def test_v1_to_v2_step_is_idempotent_on_its_own():
    once = _step_v1_to_v2(_v1_config_with_wrappers())
    twice = _step_v1_to_v2(once)
    assert twice == once


def test_migration_to_v2_is_idempotent_end_to_end():
    first, changed1 = migrate_config_dict(_v1_config_with_wrappers(), True, True)
    assert changed1 is True
    second, changed2 = migrate_config_dict(first, True, True)
    assert changed2 is False
    assert second == first



def _counting_probe(monkeypatch) -> list:
    calls: list = []

    def spy(name: str, runner=None) -> bool:
        calls.append(name)
        return name == "cld"

    monkeypatch.setattr("src.core.config_migration.probe_shell_function", spy)
    return calls


def test_already_current_config_never_probes_the_shell(tmp_path, monkeypatch):
    calls = _counting_probe(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"config_version": CURRENT_CONFIG_VERSION, "agents": {"wrappers": []}})
    )

    result = migrate_config_file(config_path)

    assert result["migrated"] is False
    assert calls == [], f"an already-current config probed the shell: {calls}"


def test_v0_config_probes_both_names_exactly_once(tmp_path, monkeypatch):
    calls = _counting_probe(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"agents": {"codex_command": "codex"}}))

    result = migrate_config_file(config_path)

    assert result["migrated"] is True
    assert len(calls) == 2
    assert set(calls) == {"cld", "cldor"}
    assert result["wrapper_ids"][:2] == ["claude", "cld"]


def test_non_object_document_neither_probes_nor_raises(tmp_path, monkeypatch):
    calls = _counting_probe(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text("[]")

    result = migrate_config_file(config_path)

    assert result["migrated"] is False
    assert calls == []
    assert config_path.read_text() == "[]"
