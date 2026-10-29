
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import tomllib
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import swarm_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import body_create, definition, memory, question_events, store, thread_port

PROJECT = "scratch-cli"


class Port:
    pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    thread_port.register(Port())
    conn = connect(db_path_for(state))
    repo = tmp_path / PROJECT
    repo.mkdir()
    agent = store.create_agent(conn, slug=f"{PROJECT}-project-agent", rank="project", job="owns the repo",
                               display_name="Scratch CLI project agent", effort="high", repo_dir=str(repo))
    body_create.write_files(state, agent, "")
    app = FastAPI()
    app.include_router(swarm_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    yield SimpleNamespace(state=state, conn=conn, agent=agent, repo=repo, app=app)
    thread_port.register(None)
    conn.close()


def test_export_carries_one_neutral_name_everywhere(env):

    async def get():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t") as c:
            return await c.get(f"/swarm/agents/{env.agent['id']}/export")

    res = asyncio.run(get())
    assert res.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(res.content))
    got = z.namelist()
    blob = "\n".join(got + [z.read(n).decode() for n in got]).lower()
    assert "scratch" not in blob and "<home>" not in blob and "<repo>" not in blob
    assert got == ["README.md", ".claude/agents/project-agent.md", ".codex/agents/project-agent.toml",
                   ".claude/agent-memory/project-agent/MEMORY.md"]
    assert res.headers["content-disposition"] == 'attachment; filename="project-agent-craft.zip"'
    assert definition.parse_definition(z.read(got[1]).decode()).name == "project-agent"
    assert tomllib.loads(z.read(got[2]).decode())["name"] == "project-agent"
    readme = z.read("README.md").decode()
    assert "claude --agent project-agent" in readme and readme.startswith("# Project agent:")


def test_export_masks_a_home_name_with_plain_words_never_html_or_angle_brackets(env):
    path = env.repo / ".claude" / "agents" / f"{env.agent['slug']}.md"
    text = path.read_text(encoding="utf-8")
    parsed = definition.parse_definition(text)
    path.write_text(text.replace(parsed.description, f"project agent for {PROJECT} at /Users/someone/{PROJECT}"), encoding="utf-8")

    async def get():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t") as c:
            return await c.get(f"/swarm/agents/{env.agent['id']}/export")

    z = zipfile.ZipFile(io.BytesIO(asyncio.run(get()).content))
    blob = "\n".join(z.read(n).decode() for n in z.namelist())
    assert "&lt;" not in blob and "&gt;" not in blob and "<home>" not in blob and "<path>" not in blob
    assert PROJECT.lower() not in blob.lower() and "/Users/" not in blob
    assert "project agent for your-project" in z.read(".claude/agents/project-agent.md").decode()
    assert "project agent for your-project" in z.read(".codex/agents/project-agent.toml").decode()


def test_a_clean_slug_is_kept(env):
    from src.core.swarm import export

    assert export.export_name({"slug": "loki-swap", "rank": "feature"}, ("acmeshop",)) == "loki-swap"
    assert export.export_name({"slug": "acmeshop-swap", "rank": "feature", "task_type": "model-swap"}, ("acmeshop",)) == "model-swap"
    assert export.export_name({"slug": "acmeshop-swap", "rank": "feature", "task_type": "acmeshop"}, ("acmeshop",)) == "feature-agent"


def _kinds(env, agent_id):
    ev = question_events._events(env.conn, agent_id, 50)
    return [(e.get("event") or e["kind"], e["id"]) for e in sorted(ev, key=lambda e: e["at"])]


def test_escalated_owner_trip_survives_the_answer(env):
    c = env.conn
    asker = env.agent["id"]
    tier = store.create_agent(c, slug="tier-one", rank="project", job="tier", display_name="Tier One", effort="low",
                              repo_dir=str(env.repo))["id"]
    c.execute("INSERT INTO swarm_questions (id, text, state, card_ref, created_at) VALUES (1, 'which flag?', 'open', '77', "
              "'2026-10-05T10:00:10Z')")
    c.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (1, ?, '2026-10-05T10:00:00Z')", (asker,))
    c.execute("INSERT INTO swarm_question_hops (question_id, agent_id, outcome, at) VALUES (1, ?, 'no_hit', '2026-10-05T10:00:05Z')",
              (tier,))
    c.commit()
    assert [k for k, _ in _kinds(env, asker)] == ["agent", "escalated"]
    c.execute("UPDATE swarm_questions SET state = 'answered', answered_by = 'owner', answer_text = 'use -x', "
              "answered_at = '2026-10-05T10:05:00Z' WHERE id = 1")
    c.commit()
    assert [k for k, _ in _kinds(env, asker)] == ["agent", "escalated"]
    assert [i for k, i in _kinds(env, asker) if k == "escalated"] == ["ev:escalated:question:1:owner"]
