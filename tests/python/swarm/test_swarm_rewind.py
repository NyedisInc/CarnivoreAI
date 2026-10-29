
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

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s5b_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s5b_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import one_shot_routes, swarm_routes
from src.api.auth import require_auth
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import delivery, say, thread_port

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
    async def archive_thread(self, thread_key): ...
    async def read_thread(self, thread_key, limit, cards=True):
        return [{"kind": "owner", "id": f"msg:{i + 1}", "at": float(i), "text": t} for i, t in enumerate(self.owner)][-limit:]
    async def tell(self, thread_key, session_id, text, *, message): ...
    async def open_cards(self): return []


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



def _stamp(state: Path, agent_id: int, uuid: str) -> None:
    with closing(connect(db_path_for(state), create=False)) as conn:
        conn.execute("UPDATE swarm_wakes SET conversation_uuid = ? WHERE id = (SELECT MAX(id) FROM swarm_wakes WHERE agent_id = ?)",
                     (uuid, agent_id))
        conn.commit()


def _row_uuid(state: Path, agent_id: int):
    with closing(connect(db_path_for(state), create=False)) as conn:
        return conn.execute("SELECT s.claude_session_uuid FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id "
                            "WHERE a.id = ?", (agent_id,)).fetchone()[0]


@pytest.mark.asyncio
async def test_rewind_restores_the_folder_in_a_new_commit_and_resume_an_earlier_conversation(world, tmp_path, monkeypatch):
    from src.core import session_agent_choice, session_imported_restart

    monkeypatch.setattr(session_agent_choice, "configured_wrapper_ids", lambda settings_obj: ["claude"])
    corpus = tmp_path / "projects"
    monkeypatch.setattr(session_imported_restart, "default_projects_dir", lambda: corpus)
    transport = httpx.ASGITransport(app=world.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
        made = await client.post(f"{API}/agents", json={"repo_dir": str(world.repo), "job": "swap models", "rank": "feature",
                                                        "effort": "high", "effort_reason": "wide change"})
        assert made.status_code == 201, made.text
        agent_id, slug = made.json()["id"], made.json()["slug"]
        memory = world.repo / ".claude" / "agent-memory" / slug
        assert (await client.get(f"{API}/agents/{agent_id}/checkpoints")).json()["commits"] == []

        async def wake_and_sleep(change) -> dict:
            woke = await client.post(f"{API}/agents/{agent_id}/wake", json={"mode": "fresh"})
            assert woke.status_code == 200, woke.text
            change()
            slept = await client.post(f"{API}/agents/{agent_id}/sleep")
            assert slept.status_code == 200 and slept.json()["commit"]["status"] == "committed", slept.text
            return slept.json()["commit"]

        first = await wake_and_sleep(lambda: (memory / "a.md").write_text("alpha one\n"))
        _stamp(world.state, agent_id, "11111111-1111-4111-8111-111111111111")
        await wake_and_sleep(lambda: ((memory / "a.md").write_text("alpha two\n"), (memory / "b.md").write_text("bravo\n")))
        await wake_and_sleep(lambda: ((memory / "a.md").write_text("alpha three\n"), (memory / "b.md").unlink()))
        listed = (await client.get(f"{API}/agents/{agent_id}/checkpoints")).json()["commits"]
        assert len(listed) >= 3 and listed[0]["kind"] == "memory" and first["sha"] in [c["sha"] for c in listed]

        (world.repo / "owner.txt").write_text("staged by the owner\n")
        git(world.repo, "add", "owner.txt")
        (world.repo / "README").write_text("edited\n")

        bad = await client.post(f"{API}/agents/{agent_id}/rewind", json={"sha": git(world.repo, "rev-list", "--max-parents=0", "HEAD").strip()})
        assert bad.status_code == 409 and "checkpoint" in bad.json()["detail"]["message"], bad.text
        (memory / "a.md").write_text("hand edit\n")
        dirty = await client.post(f"{API}/agents/{agent_id}/rewind", json={"sha": first["sha"]})
        assert dirty.status_code == 409 and "uncommitted" in dirty.json()["detail"]["message"]
        (memory / "a.md").write_text("alpha three\n")
        (world.repo / ".git" / "MERGE_HEAD").write_text(first["sha"] + "\n")
        merging = await client.post(f"{API}/agents/{agent_id}/rewind", json={"sha": first["sha"]})
        assert merging.status_code == 409 and "merge" in merging.json()["detail"]["message"]
        (world.repo / ".git" / "MERGE_HEAD").unlink()

        before = git(world.repo, "rev-list", "--count", "HEAD").strip()
        done = await client.post(f"{API}/agents/{agent_id}/rewind", json={"sha": first["sha"][:10]})
        assert done.status_code == 200 and done.json()["commit"]["status"] == "committed", done.text
        assert int(git(world.repo, "rev-list", "--count", "HEAD")) == int(before) + 1
        assert git(world.repo, "log", "-1", "--format=%s").strip() == f"swarm: {slug} memory rewound to {first['sha'][:8]}"
        assert (memory / "a.md").read_text() == "alpha one\n" and not (memory / "b.md").exists()
        assert git(world.repo, "diff", f"{first['sha']}", "HEAD", "--", f".claude/agent-memory/{slug}").strip() == ""
        files = set(git(world.repo, "show", "--name-only", "--format=", "HEAD").split())
        assert files and all(f.startswith(f".claude/agent-memory/{slug}/") for f in files), files
        assert git(world.repo, "diff", "--cached", "--name-only").split() == ["owner.txt"]
        assert git(world.repo, "diff", "--name-only").split() == ["README"]
        assert _row_uuid(world.state, agent_id) is None
        assert (await client.get(f"{API}/agents/{agent_id}/checkpoints")).json()["commits"][0]["kind"] == "rewind"

        woke = await client.post(f"{API}/agents/{agent_id}/wake", json={"mode": "resume"})
        assert woke.status_code == 200 and "--resume" not in world.argv_log.read_text().split()
        awake = await client.post(f"{API}/agents/{agent_id}/rewind", json={"sha": first["sha"]})
        assert awake.status_code == 409 and "sleep" in awake.json()["detail"]["message"]
        assert (await client.post(f"{API}/agents/{agent_id}/sleep")).status_code == 200

        uuid = "11111111-1111-4111-8111-111111111111"
        convs = (await client.get(f"{API}/agents/{agent_id}/conversations")).json()
        assert [(c["conversation_uuid"], c["transcript_present"]) for c in convs] == [(uuid, False)]
        refused = await client.post(f"{API}/agents/{agent_id}/wake", json={"conversation_uuid": uuid})
        assert refused.status_code == 409 and "transcript" in refused.json()["detail"]["message"]
        stranger = await client.post(f"{API}/agents/{agent_id}/wake", json={"conversation_uuid": "22222222-2222-4222-8222-222222222222"})
        assert stranger.status_code == 409 and "own" in stranger.json()["detail"]["message"]
        assert _open_wakes(world.state) == 0
        slug_dir = corpus / session_imported_restart.slugify_project_dir(str(world.repo))
        slug_dir.mkdir(parents=True)
        (slug_dir / f"{uuid}.jsonl").write_text("{}\n")
        assert (await client.get(f"{API}/agents/{agent_id}/conversations")).json()[0]["transcript_present"] is True
        resumed = await client.post(f"{API}/agents/{agent_id}/wake", json={"conversation_uuid": uuid})
        assert resumed.status_code == 200, resumed.text
        await _until(lambda: "--resume" in world.argv_log.read_text().split(), "the stub to log --resume")
        argv = world.argv_log.read_text().split()
        assert argv[argv.index("--resume") + 1] == uuid


@pytest.mark.asyncio
async def test_a_wake_during_a_rewind_waits_for_the_rewind_commit(world, monkeypatch):
    from src.core import session_agent_choice
    from src.core.swarm import body, sleep_commit

    monkeypatch.setattr(session_agent_choice, "configured_wrapper_ids", lambda settings_obj: ["claude"])
    transport = httpx.ASGITransport(app=world.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
        made = await client.post(f"{API}/agents", json={"repo_dir": str(world.repo), "job": "swap models", "rank": "feature",
                                                        "effort": "high", "effort_reason": "wide change"})
        assert made.status_code == 201, made.text
        agent_id, slug = made.json()["id"], made.json()["slug"]
        memory = world.repo / ".claude" / "agent-memory" / slug
        shas = []
        for text in ("alpha one\n", "alpha two\n"):
            assert (await client.post(f"{API}/agents/{agent_id}/wake", json={"mode": "fresh"})).status_code == 200
            (memory / "a.md").write_text(text)
            slept = await client.post(f"{API}/agents/{agent_id}/sleep")
            assert slept.status_code == 200, slept.text
            shas.append(slept.json()["commit"]["sha"])

        in_commit, release = asyncio.Event(), asyncio.Event()
        real_run, real_start, seen = sleep_commit.run, body._start, []

        async def slow_commit(agent, message=""):
            if "rewound" in message:
                in_commit.set()
                await release.wait()
            return await real_run(agent, message)

        async def watching_start(app_state, agent, mode):
            seen.append((memory / "a.md").read_text())
            return await real_start(app_state, agent, mode)

        monkeypatch.setattr(sleep_commit, "run", slow_commit)
        monkeypatch.setattr(body, "_start", watching_start)
        rewinding = asyncio.create_task(client.post(f"{API}/agents/{agent_id}/rewind", json={"sha": shas[0]}))
        await asyncio.wait_for(in_commit.wait(), 20)
        waking = asyncio.create_task(client.post(f"{API}/agents/{agent_id}/wake", json={"mode": "fresh"}))
        await asyncio.sleep(0.5)
        assert not waking.done() and seen == []
        release.set()
        done, woke = await rewinding, await waking
        assert done.status_code == 200 and done.json()["commit"]["status"] == "committed", done.text
        assert woke.status_code == 200, woke.text
        assert seen == ["alpha one\n"]
        assert (await client.post(f"{API}/agents/{agent_id}/sleep")).status_code == 200
