
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config.mcp import McpConfig
from src.core.mcp import agent_tool_switches
from src.core.skills.required import STATE_AVAILABLE, STATE_INSTALLED
from tests.skill_manager.test_required_skills import ITEM_ID, V1, env  # noqa: F401

pytestmark = pytest.mark.real_agent_tool_switches


@pytest.fixture
def huddle(monkeypatch):
    cfg = McpConfig()
    monkeypatch.setattr(agent_tool_switches, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    return cfg


def _trash(env) -> list:  # noqa: F811
    return list((env.roots.home / ".claude" / ".carnivore-trash").glob("huddle-*"))


def test_switched_off_the_pass_never_installs_the_huddle_skill(env, huddle) -> None:  # noqa: F811
    env.run_pass()
    assert not env.claude().exists() and not env.codex().exists()
    assert [r.item_id for r in env.rows()] == []
    assert env.state()["state"] == STATE_AVAILABLE


def test_turned_on_it_installs_and_turned_off_a_pristine_copy_goes_to_the_trash(env, huddle) -> None:  # noqa: F811
    huddle.agent_huddle_tools = True
    env.run_pass()
    assert (env.claude() / "SKILL.md").read_text(encoding="utf-8") == V1
    huddle.agent_huddle_tools = False
    env.run_pass()
    assert not env.claude().exists() and not env.codex().exists()
    assert env.rows() == []
    trashed = _trash(env)
    assert len(trashed) == 1 and (trashed[0] / "SKILL.md").read_text(encoding="utf-8") == V1
    assert env.state()["state"] == STATE_AVAILABLE
    huddle.agent_huddle_tools = True
    env.run_pass()
    assert env.state()["state"] == STATE_INSTALLED


def test_turned_off_a_copy_the_person_edited_is_never_touched(env, huddle) -> None:  # noqa: F811
    huddle.agent_huddle_tools = True
    env.run_pass()
    (env.claude() / "SKILL.md").write_text(V1 + "my own rule\n", encoding="utf-8")
    huddle.agent_huddle_tools = False
    env.run_pass()
    assert (env.claude() / "SKILL.md").read_text(encoding="utf-8") == V1 + "my own rule\n"
    assert (env.codex() / "SKILL.md").read_text(encoding="utf-8") == V1
    assert [r.item_id for r in env.rows()] == [ITEM_ID]
    assert _trash(env) == []


def test_turned_off_a_folder_this_app_never_installed_is_left_alone(env, huddle) -> None:  # noqa: F811
    mine = env.claude()
    mine.mkdir()
    (mine / "SKILL.md").write_text(V1, encoding="utf-8")
    env.run_pass()
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == V1
    assert env.rows() == [] and _trash(env) == []
