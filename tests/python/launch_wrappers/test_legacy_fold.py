
from __future__ import annotations

import copy
import json
import subprocess

import pytest

from src.config.agent_command import agent_command
from src.config.agents import AgentsConfig
from src.core.agent_families import AGENT_FAMILIES
from src.core.config_migration import CURRENT_CONFIG_VERSION, migrate_config_file
from src.core.launch_wrappers.legacy_fold import fold_legacy_commands
from src.core.session_restart import resume_arguments

UUID = "9f27394c-7842-4fb8-87b7-6aa0543ae908"

FIXTURE = {
    "config_version": 5,
    "projects": [],
    "agents": {
        "claude_command": "claude --dangerously-skip-permissions",
        "codex_command": "codex --yolo",
        "hermes_command": "hermes",
        "openclaw_command": "openclaw tui --profile work",
        "local_command": "cldl --fast",
        "shell_command": "/bin/bash -l",
        "wrappers": [
            {"id": "claude-skip-permissions", "family": "claude", "label": "claude",
             "script": 'command claude --dangerously-skip-permissions "$@"',
             "default": True, "accepts_model": False},
            {"id": "keyc", "family": "claude", "label": "keyc", "script": "keyc() { :; }",
             "entry": "keyc", "default": False, "accepts_model": False},
            {"id": "cldl", "family": "local", "label": "cldl", "script": "cldl() { :; }",
             "entry": "cldl", "default": False, "accepts_model": True},
        ],
    },
}


@pytest.fixture()
def migrated(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(FIXTURE, indent=2))
    before = path.read_bytes()
    result = migrate_config_file(path)
    assert result["migrated"] is True
    return path, before, json.loads(path.read_text())


def _family(data, name):
    return [w for w in data["agents"]["wrappers"] if (w.get("family") or "claude") == name]


def test_the_marker_is_stamped_and_the_backup_is_the_original(migrated):
    path, before, after = migrated
    assert after["config_version"] == CURRENT_CONFIG_VERSION == 8
    assert path.with_name("config.json.bak").read_bytes() == before


def test_a_rerun_is_a_no_op(migrated):
    path, _before, _after = migrated
    written = path.read_bytes()
    backup = path.with_name("config.json.bak").read_bytes()
    assert migrate_config_file(path)["migrated"] is False
    assert path.read_bytes() == written
    assert path.with_name("config.json.bak").read_bytes() == backup


def test_a_customised_command_with_no_wrapper_becomes_the_familys_default(migrated):
    _path, _before, after = migrated
    [codex] = _family(after, "codex")
    assert (codex["id"], codex["script"], codex["default"]) == (
        "codex-default", 'codex "$@" --yolo', True)
    [openclaw] = _family(after, "openclaw")
    assert openclaw["script"] == 'openclaw tui --profile work "$@"'
    assert openclaw["default"] is True
    [shell] = _family(after, "shell")
    assert shell["script"] == '/bin/bash -l "$@"'


def test_an_untouched_command_gets_the_standard_wrapper(migrated):
    _path, _before, after = migrated
    [hermes] = _family(after, "hermes")
    assert hermes["script"] == 'hermes "$@"' and hermes["default"] is True


def test_a_family_with_wrappers_keeps_launching_them(migrated):
    _path, _before, after = migrated
    claude = _family(after, "claude")
    assert [(w["id"], w["default"]) for w in claude] == [
        ("claude-skip-permissions", True), ("keyc", False)]
    local = _family(after, "local")
    assert [(w["id"], w["default"]) for w in local] == [("cldl", True), ("local-legacy", False)]
    assert local[1]["script"] == 'cldl --fast "$@"'
    assert local[1]["accepts_model"] is True


def test_no_customised_value_is_lost_and_the_keys_stay_inert(migrated):
    _path, _before, after = migrated
    for key in ("claude_command", "codex_command", "hermes_command",
                "openclaw_command", "local_command", "shell_command"):
        assert after["agents"][key] == FIXTURE["agents"][key]
    scripts = " ".join(w["script"] for w in after["agents"]["wrappers"])
    for custom in ("codex \"$@\" --yolo", "openclaw tui --profile work",
                   "cldl --fast", "/bin/bash -l"):
        assert custom in scripts


def test_every_family_ends_with_exactly_one_default(migrated):
    _path, _before, after = migrated
    for family in AGENT_FAMILIES:
        flags = [w for w in _family(after, family.name) if w.get("default")]
        assert len(flags) == 1, family.name
    AgentsConfig(**after["agents"])


def test_the_step_never_mutates_its_input():
    data = copy.deepcopy(FIXTURE)
    fold_legacy_commands(data)
    assert data == FIXTURE


def test_a_folded_codex_resume_runs_the_subcommand_before_the_flags(migrated, tmp_path):
    _path, _before, after = migrated
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record = tmp_path / "argv.txt"
    codex = fake_bin / "codex"
    codex.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{record}'\n")
    codex.chmod(0o755)

    command = agent_command(
        "codex",
        agents=AgentsConfig(**after["agents"]),
        resolve_state_dir=lambda: str(tmp_path / "state"),
        disable_alternate_screen=lambda: True,
        extra_args=resume_arguments(UUID, family="codex"),
    )
    subprocess.run(["/bin/sh", "-c", command], check=True, timeout=30,
                   env={"HOME": str(tmp_path), "PATH": f"{fake_bin}:/usr/bin:/bin"})
    assert record.read_text().splitlines() == ["resume", UUID, "--no-alt-screen", "--yolo"]


def test_a_legacy_command_a_wrapper_already_runs_is_not_duplicated():
    data = {"agents": {
        "claude_command": "claude --dangerously-skip-permissions",
        "wrappers": [{"id": "claude-skip-permissions", "family": "claude", "label": "c",
                      "script": 'command claude --dangerously-skip-permissions "$@"',
                      "default": True}],
    }}
    out = fold_legacy_commands(data)
    assert [w["id"] for w in _family(out, "claude")] == ["claude-skip-permissions"]


def test_a_shape_this_step_does_not_know_is_returned_unchanged():
    assert fold_legacy_commands({"agents": "nonsense"}) == {"agents": "nonsense"}
    assert fold_legacy_commands({"agents": {"wrappers": "x"}}) == {"agents": {"wrappers": "x"}}
