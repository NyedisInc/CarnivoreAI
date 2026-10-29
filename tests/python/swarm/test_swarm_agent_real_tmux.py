
from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s1_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s1_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import one_shot_routes, swarm_routes
from src.api.auth import require_auth
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import delivery, thread_port
from src.core.swarm.owner_message import REF_LINE

API = "/swarm"


class FakePort:

    def __init__(self) -> None:
        self.owner: list = []

    async def ensure_thread(self, thread_key, title): ...
    async def post_card(self, thread_key, kind, title, text, swarm_ref): return 1
    async def post_owner_message(self, thread_key, text):
        self.owner.append(text)
        return f"huddle:msg:{len(self.owner)}"
    async def post_traffic(self, thread_key, text, swarm_ref): return "huddle:msg:0"
    async def close_card(self, item_id, state): ...
    async def close_open_cards(self, thread_key, prefix): ...
    async def open_cards(self): return []
    async def archive_thread(self, thread_key): ...
    async def read_thread(self, thread_key, limit, cards=True):
        return [{"kind": "owner", "id": f"msg:{i + 1}", "at": float(i), "text": t} for i, t in enumerate(self.owner)][-limit:]
    async def tell(self, thread_key, session_id, text, *, message): ...


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}).stdout


@pytest.fixture()
def world(tmp_path, monkeypatch, tmux_test_socket):
    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"config_version": 5, "projects": [], "mcp": {"enabled": False}}))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    monkeypatch.setattr(settings, "_auth_config_cache", None)
    assert ensure_db_migrated(state).status == "ok"

    stub = tmp_path / "stubagent"
    argv_log, inbox = tmp_path / "argv.txt", tmp_path / "inbox.txt"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{argv_log}'\nexec cat >> '{inbox}'\n")
    stub.chmod(0o755)
    monkeypatch.setattr(type(settings), "get_agent_command",
                        lambda self, agent_type, model=None, extra_args=None, **kw:
                        f"{shlex.quote(str(stub))} " + " ".join(shlex.quote(a) for a in (extra_args or [])))

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "README").write_text("one\n")
    git(repo, "add", "README")
    git(repo, "commit", "-q", "-m", "init")

    pasted, busy = [], {"on": False}

    async def fake_paste(request, session_id, text, **kw):
        if busy["on"]:
            raise HTTPException(status_code=409, detail={"code": "pane_dialog_open", "message": "busy"})
        pasted.append(text)

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", fake_paste)
    monkeypatch.setattr(delivery, "RETRY_S", 0.1)
    port = FakePort()
    thread_port.register(port)

    from src.core.session_manager import SessionManager

    manager = SessionManager()

    class Servers:
        async def clear_session(self, name): ...

    app = FastAPI()
    app.include_router(swarm_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = manager
    app.state.local_servers = Servers()
    app.state.attention_watcher = None
    yield SimpleNamespace(app=app, repo=repo, state=state, pasted=pasted, busy=busy, manager=manager, port=port,
                          argv_log=argv_log)
    thread_port.register(None)
    delivery._pending.clear()
    for name in _bodies(manager):
        subprocess.run(["tmux", "-L", manager.tmux_socket_name(), "kill-session", "-t", f"={name}"], check=False)
    settings._auth_config_cache = None


def _bodies(manager) -> list:
    return subprocess.run(["tmux", "-L", manager.tmux_socket_name(), "list-sessions", "-F", "#{session_name}"],
                          capture_output=True, text=True, check=False).stdout.split()


def _open_wakes(state: Path) -> int:
    with closing(connect(db_path_for(state), create=False)) as conn:
        return conn.execute("SELECT COUNT(*) FROM swarm_wakes WHERE ended_at IS NULL").fetchone()[0]


async def _until(check, what: str, timeout: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        assert asyncio.get_running_loop().time() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_owner_message_wakes_one_body_queues_a_second_and_sleep_commits_memory_only(world):
    transport = httpx.ASGITransport(app=world.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
        made = await client.post(f"{API}/agents", json={"repo_dir": str(world.repo), "job": "swap models",
                                                        "rank": "feature", "effort": "high", "effort_reason": "wide change"})
        assert made.status_code == 201, made.text
        agent = made.json()
        agent_id, slug = agent["id"], agent["slug"]
        assert agent["state"] == "asleep" and agent["session_id"] is None
        assert _bodies(world.manager) == []

        world.busy["on"] = True
        first = await client.post(f"{API}/agents/{agent_id}/messages", json={"text": "swap the models"})
        assert first.status_code == 200, first.text
        assert first.json()["outcome"] == "waking" and first.json()["message_ref"] == "huddle:msg:1"
        detail = (await client.get(f"{API}/agents/{agent_id}")).json()
        assert detail["state"] == "awake" and detail["session_id"] and detail["tmux_session"]
        assert _bodies(world.manager) == [detail["tmux_session"]] and _open_wakes(world.state) == 1
        await _until(world.argv_log.exists, "the stub agent to start")
        assert world.argv_log.read_text().splitlines()[:2] == ["--agent", slug]

        second = await client.post(f"{API}/agents/{agent_id}/messages", json={"text": "and keep the tests green"})
        assert second.status_code == 200 and second.json()["outcome"] in ("held", "waking")
        assert _bodies(world.manager) == [detail["tmux_session"]] and _open_wakes(world.state) == 1
        assert world.pasted == []
        world.busy["on"] = False
        await _until(lambda: len(world.pasted) == 2, "both queued texts to land")
        assert "desk" in world.pasted[0] and world.pasted[1] == f"and keep the tests green\n\n{REF_LINE.format(ref='huddle:msg:2')}"
        with closing(connect(db_path_for(world.state), create=False)) as conn:
            rows = conn.execute("SELECT authority, source FROM swarm_deliveries ORDER BY id").fetchall()
        assert [(r[0], r[1]) for r in rows] == [("owner", "wake_prompt"), ("owner", "owner_chat")]
        page = (await client.get(f"{API}/agents/{agent_id}/conversation")).json()
        assert [e["text"] for e in page["entries"]] == ["swap the models", "and keep the tests green"]

        memory = world.repo / ".claude" / "agent-memory" / slug
        (memory / "fact.md").write_text("---\nname: fact\n---\nthe models live in models.py\n")
        (world.repo / "owner.txt").write_text("staged by the owner\n")
        git(world.repo, "add", "owner.txt")
        (world.repo / "README").write_text("two\n")
        slept = await client.post(f"{API}/agents/{agent_id}/sleep")
        assert slept.status_code == 200, slept.text
        assert slept.json()["state"] == "asleep" and slept.json()["commit"]["status"] == "committed"
        sha = slept.json()["commit"]["sha"]
        changed = set(git(world.repo, "show", "--name-only", "--format=", sha).split())
        assert changed and all(p.startswith((f".claude/agent-memory/{slug}/", f".claude/agents/{slug}.md",
                                             f".codex/agents/{slug}.toml")) for p in changed), changed
        assert ".claude/agent-memory/%s/fact.md" % slug in changed
        assert git(world.repo, "diff", "--cached", "--name-only").split() == ["owner.txt"]
        assert git(world.repo, "diff", "--name-only").split() == ["README"]
        after = (await client.get(f"{API}/agents/{agent_id}")).json()
        assert after["state"] == "asleep" and after["session_id"] is None
        assert _bodies(world.manager) == [] and _open_wakes(world.state) == 0
