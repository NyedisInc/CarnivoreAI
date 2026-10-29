
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

USER_DATA_KEYS = ()


@pytest.fixture(scope="module")
def example() -> dict:
    return json.loads((REPO_ROOT / "config.example.json").read_text())


def test_example_config_seeds_no_user_data(example: dict) -> None:
    for key in USER_DATA_KEYS:
        assert key in example, (
            f"{key} vanished from config.example.json. The example must still "
            f"document the key's existence and type, or the file stops being a "
            f"description of the file's shape."
        )
        assert example[key] == [], (
            f"config.example.json seeds {len(example[key])} {key}. The bootstrap "
            f"copies this file verbatim to config.json, so every entry here "
            f"becomes a row on a brand-new user's very first screen, pointing at "
            f"a path that exists only on the machine of whoever wrote it."
        )


def test_example_config_carries_no_projects_key(example: dict) -> None:
    assert "projects" not in example, (
        "config.example.json still carries a projects key. Projects live "
        "in cloude.db only, so a key here documents a shape the app does "
        "not read and invites hand edits that silently do nothing."
    )
    assert "_comment_projects" not in example, (
        "config.example.json still documents the retired projects array's "
        "entry shape. That is now a stale doc."
    )
    retired = example.get("_comment_projects_retired")
    assert isinstance(retired, str) and "cloude.db" in retired, (
        "config.example.json should say where projects DID go. Removing "
        "the key without a forwarding note leaves a reader who remembers "
        "it with no way to find out what replaced it."
    )


def test_fresh_config_json_yields_zero_projects(tmp_path: Path) -> None:
    fresh = tmp_path / "config.json"
    fresh.write_bytes((REPO_ROOT / "config.example.json").read_bytes())
    loaded = json.loads(fresh.read_text())
    assert not loaded.get("projects"), (
        "A freshly bootstrapped config.json contains projects. The first "
        "screen of a brand-new install would show rows the user never made."
    )
