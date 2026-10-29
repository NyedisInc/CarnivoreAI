
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import pytest

from src.config import AgentsConfig
from src.config.agent_command import agent_command
from src.core.agent_families import (
    AGENT_FAMILIES,
    get_family,
)
from src.core.shell_init import RC_SOURCE

TOOL_FAMILIES = ("claude", "codex", "hermes", "openclaw", "local")


@pytest.mark.parametrize("name", TOOL_FAMILIES)
def test_a_tool_family_sources_the_users_rc(name):
    assert get_family(name).sources_zshrc is True, (
        f"{name} launches a user-installed CLI but does not source ~/.zshrc; "
        "a version-manager install will not be on PATH in a tmux pane"
    )


def test_the_shell_family_does_not_source_the_rc():
    assert get_family("shell").sources_zshrc is False


def _launch(name, tmp_path):
    return agent_command(
        name,
        agents=AgentsConfig(),
        resolve_state_dir=lambda: str(tmp_path),
        disable_alternate_screen=lambda: False,
        model="some/model" if get_family(name).needs_model else None,
    )


@pytest.mark.parametrize("name", TOOL_FAMILIES)
def test_the_standard_wrapper_is_rendered_rc_sourced(name, tmp_path):
    rendered = _launch(name, tmp_path)
    assert RC_SOURCE in rendered, rendered
    assert rendered.startswith("zsh -c ")


def test_the_shell_standard_wrapper_does_not_source_the_rc(tmp_path):
    rendered = _launch("shell", tmp_path)
    assert RC_SOURCE not in rendered, rendered


def test_every_family_declares_the_column_deliberately():
    covered = set(TOOL_FAMILIES) | {"shell"}
    assert {f.name for f in AGENT_FAMILIES} == covered, (
        "a family was added or removed; decide its sources_zshrc value "
        "and record the reason in this test"
    )
