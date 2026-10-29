
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.wrappers import ensure_defaults
from src.core.agent_families import AGENT_FAMILIES, AGENT_FAMILY_BY_NAME
from src.core.agent_wrappers import AgentWrapper
from src.core.launch_wrappers.family_defaults import (
    ensure_family_defaults,
    same_launch,
    script_from_command,
    unique_id,
)
from tests.helpers.wrapper_seeds import stored_wrappers


def _by_family(wrappers):
    out = {}
    for w in wrappers:
        out.setdefault(w.get("family") or "claude", []).append(w)
    return out


def test_an_empty_list_gets_one_valid_default_per_family():
    seeded = ensure_family_defaults([])
    groups = _by_family(seeded)
    assert set(groups) == {f.name for f in AGENT_FAMILIES}
    for family in AGENT_FAMILIES:
        [only] = groups[family.name]
        assert only["default"] is True
        assert only["id"] == family.default_wrapper_id
        assert only["script"] == family.default_script
        AgentWrapper(**only)


def test_seeding_is_idempotent():
    once = ensure_family_defaults([])
    assert ensure_family_defaults(once) == once


def test_a_users_wrapper_is_never_rewritten_or_joined_by_a_seed():
    mine = {"id": "my-codex", "family": "codex", "label": "mine",
            "script": "codex --yolo \"$@\"", "default": True}
    result = ensure_family_defaults([dict(mine)])
    codex = _by_family(result)["codex"]
    assert codex == [mine]


def test_a_family_with_no_flag_gets_it_on_the_wrapper_that_already_launched():
    result = ensure_family_defaults([
        {"id": "a", "family": "local", "label": "a", "script": "cldl \"$@\""},
        {"id": "b", "family": "local", "label": "b", "script": "cldl \"$@\""},
    ])
    local = _by_family(result)["local"]
    assert [(w["id"], w.get("default")) for w in local] == [("a", True), ("b", None)]


def test_two_flags_from_a_hand_edit_keep_the_first():
    result = ensure_family_defaults([
        {"id": "a", "family": "claude", "label": "a", "script": "x", "default": True},
        {"id": "b", "family": "claude", "label": "b", "script": "y", "default": True},
    ])
    claude = _by_family(result)["claude"]
    assert [w["default"] for w in claude] == [True, False]


def test_a_seed_never_takes_an_id_another_family_already_uses():
    taken = {"id": "codex-default", "family": "claude", "label": "odd", "script": "x",
             "default": True}
    result = ensure_family_defaults([taken])
    codex = _by_family(result)["codex"]
    assert [w["id"] for w in codex] == ["codex-default-2"]
    assert unique_id("x", {"x", "x-2"}) == "x-3"


def test_a_non_dict_entry_is_kept_in_place():
    result = ensure_family_defaults(["junk"])
    assert result[0] == "junk"


@pytest.mark.parametrize("family,command,script", [
    ("codex", "codex --yolo", 'codex "$@" --yolo'),
    ("codex", "codex", 'codex "$@"'),
    ("claude", "claude --x", 'claude --x "$@"'),
    ("shell", "/bin/bash -l", '/bin/bash -l "$@"'),
    ("claude", 'keyc "$@"', 'keyc "$@"'),
])
def test_script_from_command_forwards_where_the_static_path_did(family, command, script):
    assert script_from_command(family, command) == script


def test_same_launch_ignores_command_prefix_and_forwarding():
    assert same_launch("claude --x", 'command claude --x "$@"')
    assert not same_launch("claude --x", 'claude --y "$@"')
    assert not same_launch("claude", "line one\nline two")




def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def test_ensure_defaults_writes_once_with_a_backup_then_never_again(tmp_path):
    path = tmp_path / "config.json"
    original = {"config_version": 6, "agents": {"wrappers": [
        {"id": "keyc", "family": "claude", "label": "keyc", "script": "keyc \"$@\"", "default": True},
    ]}, "projects": []}
    _write(path, original)

    assert ensure_defaults(path) is True
    backup = path.with_name("config.json.bak")
    assert json.loads(backup.read_text()) == original
    first = path.read_bytes()
    written = json.loads(first)
    assert stored_wrappers(written)[0] == stored_wrappers(original)[0]
    assert {w["family"] for w in stored_wrappers(written)} == set(AGENT_FAMILY_BY_NAME)

    backup_before = backup.read_bytes()
    assert ensure_defaults(path) is False
    assert path.read_bytes() == first
    assert backup.read_bytes() == backup_before


def test_ensure_defaults_leaves_a_config_with_nothing_due_byte_identical(tmp_path):
    path = tmp_path / "config.json"
    _write(path, {"agents": {"wrappers": ensure_family_defaults([])}})
    before = path.read_bytes()
    assert ensure_defaults(path) is False
    assert path.read_bytes() == before
    assert not path.with_name("config.json.bak").exists()


def test_ensure_defaults_refuses_a_shape_it_does_not_know(tmp_path):
    path = tmp_path / "config.json"
    _write(path, {"agents": {"wrappers": "nonsense"}})
    before = path.read_bytes()
    assert ensure_defaults(path) is False
    assert path.read_bytes() == before
