
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_create_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_create_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp.caller import AgentCaller
from src.core.swarm import definition, guard, store

RENAMED = {"task_manager_fork": "huddle_fork", "task_manager_group_create": "huddle_group_create"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    guard.reset()
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        for name, rank in (("sysop", "alpha"), ("acme", "company"), ("loki", "feature")):
            conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin, "
                "lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, '/tmp/pk', 't', 'created', 'running', "
                "'2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{name}", f"cloude_{name}"))
            row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{name}",)).fetchone()[0]
            agent = store.create_agent(conn, slug=name, rank=rank, job="j", display_name=name, repo_dir=f"/tmp/pk-{name}", effort="high")
            store.set_session_row(conn, agent["id"], row_id)
    yield SimpleNamespace(state=tmp_path)
    guard.reset()


def _pane(name: str) -> AgentCaller:
    return AgentCaller(f"ses_{name}", f"cloude_{name}", f"ses_{name}")


@pytest.mark.parametrize("rank", ["company", "alpha"])
def test_a_settings_file_denies_both_spellings_of_every_renamed_create_tool(rank):
    deny = json.loads(definition.render_settings(Path("/memory"), rank))["permissions"]["deny"]
    for new, old in RENAMED.items():
        assert f"mcp__carnivore__{new}" in deny and f"mcp__carnivore__{old}" in deny, (rank, new)
    assert "mcp__carnivore__swarm_spawn" in deny


def test_a_project_agents_settings_deny_no_create_tool():
    deny = json.loads(definition.render_settings(Path("/memory"), "project"))["permissions"]["deny"]
    assert not [d for d in deny if d.startswith("mcp__carnivore__")]


@pytest.mark.parametrize("tool", sorted(RENAMED))
@pytest.mark.parametrize("who", ["sysop", "acme"])
def test_the_server_refuses_a_company_or_sysop_pane_even_when_its_settings_file_predates_the_rename(env, who, tool):
    assert asyncio.run(guard.create_refusal(_pane(who), tool)) == guard.CREATE_REFUSAL
    assert asyncio.run(guard.refusal(_pane(who), tool)) == guard.CREATE_REFUSAL


@pytest.mark.parametrize("tool", sorted(RENAMED))
def test_a_feature_agent_a_plain_pane_and_a_token_are_not_refused(env, tool):
    assert asyncio.run(guard.create_refusal(_pane("loki"), tool)) is None
    assert asyncio.run(guard.create_refusal(_pane("nobody"), tool)) is None
    assert asyncio.run(guard.create_refusal(AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "write"), tool)) is None


def test_a_tool_that_creates_nothing_is_not_checked(env):
    assert asyncio.run(guard.create_refusal(_pane("acme"), "task_manager_tasks_list")) is None
