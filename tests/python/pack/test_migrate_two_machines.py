
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_migrate_routes as migrate_routes  # noqa: E402
from src.api import federation_pack_transport_routes as transport_routes  # noqa: E402
from src.api import pack_migrate_env as env_mod  # noqa: E402
from src.api import peer_auth  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.companies import store as companies  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants  # noqa: E402
from src.core.pack.identity import home  # noqa: E402
from src.core.pack.machines import config_state, restrictions  # noqa: E402
from src.core.pack.migrate import apply, task_manager_side, plan, transcripts  # noqa: E402
from src.core.project_writes import create_project  # noqa: E402
from src.core.swarm import store as swarm_store  # noqa: E402
from src.core.claude_transcript_correlate import slugify_project_dir  # noqa: E402


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


class Machine:

    def __init__(self, tmp: Path, name: str, install_id: str) -> None:
        self.name, self.install_id = name, install_id
        self.state, self.projects, self.claude = tmp / f"{name}-state", tmp / f"{name}-projects", tmp / f"{name}-claude"
        for folder in (self.state, self.projects, self.claude):
            folder.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        self.restrictions = restrictions.Restrictions()
        self.app = FastAPI()
        self.app.include_router(migrate_routes.router, prefix="/api/v1")
        self.app.include_router(transport_routes.router, prefix="/api/v1")
        self.client = TestClient(self.app)

    def conn(self):
        return connect(db_path_for(self.state), create=False)

    def project(self, uid: str):
        with closing(self.conn()) as conn:
            return conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone()


@pytest.fixture()
def world(monkeypatch, tmp_path):
    a, b = Machine(tmp_path, "a", "iid-a"), Machine(tmp_path, "b", "iid-b")
    machines = {"iid-a": a, "iid-b": b}
    current = [a]
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: current[0].state, raising=True)
    monkeypatch.setattr(env_mod, "_install_id", lambda: current[0].install_id)
    monkeypatch.setattr(env_mod, "_labels", lambda: {"iid-a": "mac", "iid-b": "studio"})
    monkeypatch.setattr(transcripts, "transcript_roots", lambda: (current[0].claude,))
    monkeypatch.setattr(config_state, "default", lambda: type("S", (), {"restrictions": lambda self: current[0].restrictions})())
    real_target = env_mod.target_env
    monkeypatch.setattr(env_mod, "target_env", lambda: dataclasses.replace(
        real_target(), projects_dir=str(current[0].projects), transcripts_root=current[0].claude))

    def link(sender: Machine, receiver: Machine):
        with closing(receiver.conn()) as conn:
            if not any(g.peer_install_id == sender.install_id for g in grants.list_grants(conn)):
                key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([7]) * 32))
                grants.create_grant(conn, peer_install_id=sender.install_id, public_key=key, label=sender.install_id, scopes=("migrate",))
            grant = next(g for g in grants.list_grants(conn) if g.peer_install_id == sender.install_id)
        principal = peer_auth.Principal("peer", grant)
        receiver.app.dependency_overrides[migrate_routes._require_migrate] = lambda: principal
        receiver.app.dependency_overrides[transport_routes._require_replica] = lambda: principal

        async def request(method: str, path: str, *, content: Any = None, headers: Any = None, json: Any = None):
            before = current[0]
            current[0] = receiver
            try:
                reply = receiver.client.request(method, "/api/v1" + path, content=content, headers=headers, json=json)
            finally:
                current[0] = before
            return reply.status_code, reply.json()

        return request

    monkeypatch.setattr(env_mod, "link_request", lambda install_id, timeout=0: link(current[0], machines[install_id]))
    return a, b, current, link


def seed(a: Machine) -> str:
    root = a.projects / "trader"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "main.py").write_text("print('hi')\n")
    git(root, "add", "main.py")
    git(root, "commit", "-q", "-m", "first")
    with closing(a.conn()) as conn:
        project = create_project(conn, name="trader", path=str(root))
        company = companies.create_company(conn, "acme")
        companies.assign_project(conn, project["id"], company["id"])
        swarm_store.create_agent(conn, slug="alpha", rank="project", job="lead", display_name="Alpha", repo_dir=str(root), effort="high",
                                 project_id=project["id"], company_id=company["id"])
        uid = conn.execute("SELECT uid FROM projects WHERE id = ?", (project["id"],)).fetchone()[0]
        pid = project["id"]
    items = [{"id": 1, "text": "thread", "note": "", "position": 0, "created_by": "joe", "state": "open", "created_at": 1.0, "updated_at": 1.0, "kind": ""},
             {"id": 2, "text": "the card", "note": "", "position": 1, "created_by": "joe", "state": "open", "created_at": 1.0, "updated_at": 1.0, "kind": "card"}]
    messages = [{"id": 1, "item_id": 1, "author": "joe", "kind": "text", "text": "hello", "created_at": 1.0}]
    task_manager_side.import_list(str(a.state), str(pid), {"items": items, "messages": messages, "groups": []}, {})
    folder = a.claude / slugify_project_dir(str(root))
    folder.mkdir()
    (folder / "0a1b2c3d.jsonl").write_text('{"type":"user"}\n')
    return uid


def test_migrate_to_b_verify_flip_and_move_back(world) -> None:
    a, b, current, link = world
    uid = seed(a)
    with closing(a.conn()) as conn:
        source_project = dict(conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone())
    head = git(Path(source_project["root"]), "rev-parse", "HEAD")
    env = env_mod.source_env()

    b.restrictions = restrictions.Restrictions(may_receive_projects=False)
    with pytest.raises(plan.MigrateError) as refused:
        asyncio.run(plan.plan_project(env, source_project, "iid-b", apply.guarded(link(a, b))))
    assert (refused.value.code, refused.value.rule, refused.value.status) == ("pack_restricted", "may_receive_projects", 403)
    assert b.project(uid) is None
    b.restrictions = restrictions.Restrictions()

    with closing(b.conn()) as conn:
        for filler in ("f1", "f2"):
            create_project(conn, name=filler, path=str(b.projects / filler))
    made = asyncio.run(plan.plan_project(env, source_project, "iid-b", apply.guarded(link(a, b))))
    assert made.rung == "carried" and made.case == "new" and not made.blocking, made.view()
    assert made.summary["agents"] == 1 and made.summary["cards"] == 2 and made.summary["transcript_files"] == 1
    flipped = asyncio.run(apply.apply_project(env, made, link(a, b)))
    assert flipped["machine"] == "studio"

    on_b = b.project(uid)
    assert on_b["pack_state"] == "home" and on_b["root"] == str(b.projects / "trader")
    assert git(Path(on_b["root"]), "rev-parse", "HEAD") == head
    with closing(b.conn()) as conn:
        assert [r["state"] for r in conn.execute("SELECT state FROM swarm_agents WHERE project_id = ?", (on_b["id"],))] == ["asleep"]
        company = conn.execute("SELECT name FROM companies WHERE id = ?", (on_b["company_id"],)).fetchone()
    assert company["name"] == "acme"
    with closing(b.conn()) as conn:
        assert conn.execute("SELECT thread_key FROM swarm_agents WHERE project_id = ?", (on_b["id"],)).fetchone()[0] == str(on_b["id"])
    assert task_manager_side.counts(str(b.state), str(on_b["id"])) == {"items": 2, "messages": 1, "groups": 0}
    assert (b.claude / slugify_project_dir(on_b["root"]) / "0a1b2c3d.jsonl").read_text() == '{"type":"user"}\n'

    on_a = a.project(uid)
    assert (on_a["pack_state"], on_a["moved_to_install_id"]) == ("moved_away", "iid-b")
    assert os.path.isdir(on_a["root"]), "the source is kept"
    with closing(a.conn()) as conn:
        assert home.moved_away_for(conn, on_a["root"]) is not None

    status, answer = asyncio.run(link(a, b)("POST", "/federation/pack/migrate/back", json={"op_id": "back-op-0001", "project_uid": uid}))
    assert status == 200, answer
    assert a.project(uid)["pack_state"] == "home" and a.project(uid)["moved_to_install_id"] is None
    assert b.project(uid)["pack_state"] == "moved_away" and b.project(uid)["moved_to_install_id"] == "iid-a"
    with closing(a.conn()) as conn:
        assert [r["state"] for r in conn.execute("SELECT state FROM swarm_agents WHERE project_id = ?", (on_a["id"],))] == ["asleep"]
    assert task_manager_side.counts(str(a.state), str(on_a["id"])) == {"items": 2, "messages": 1, "groups": 0}
    assert git(Path(on_a["root"]), "rev-parse", "HEAD") == head


def test_a_project_move_stops_its_live_agents_itself_and_a_turn_that_never_ends_changes_nothing(world) -> None:
    import signal
    from types import SimpleNamespace

    from src.core.pack.migrate import live
    from src.core.pack.move import session_move

    a, b, current, link = world
    uid = seed(a)
    with closing(a.conn()) as conn:
        project = dict(conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone())
        for session_uuid, title, claude, lifecycle in (("sess-luigi", "luigi", "c-luigi", "running"), ("sess-mario", "kestrel", "c-mario", "running"), ("sess-peach", "peach", "c-peach", "stopped")):
            conn.execute(
                "INSERT INTO sessions (session_uuid, project_id, working_dir, tmux_name, tmux_created_epoch, origin, agent_type, agent_family, "
                "agent_family_source, claude_session_uuid, claude_session_uuid_source, title, lifecycle, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, 'created', 'claude', 'claude', 'launch', ?, 'registry', ?, ?, 't', 't')",
                (session_uuid, project["id"], project["root"], f"carnivore_{title}", claude, title, lifecycle))
        conn.commit()
    events: list = []
    tree = subprocess.Popen(["sh", "-c", "sleep 60 & wait"], start_new_session=True)
    state = {"shells": True, "mario_finds": 0, "mario_ends": True}

    async def find(session_uuid: str) -> Any:
        if session_uuid == "sess-luigi":
            return SimpleNamespace(activity_status="idle", activity_hint="shell" if state["shells"] else None, startup_gate="ready",
                                   background_open=1 if state["shells"] else None)
        state["mario_finds"] += 1
        busy = not state["mario_ends"] or state["mario_finds"] < 8
        return SimpleNamespace(activity_status="working" if busy else "idle", activity_hint=None, startup_gate="ready")

    async def background_members(session_uuid: str) -> list:
        events.append("measure_shells")
        return [(tree.pid, "unused")]

    async def stop_members(session_uuid: str, members: list) -> list:
        events.append("stop_shells")
        assert any(e.startswith("sleep:") for e in events), "the shells are stopped only after the agents are asleep"
        os.killpg(tree.pid, signal.SIGKILL)
        tree.wait()
        state["shells"] = False
        return [tree.pid]

    async def sleep(session_uuid: str) -> None:
        assert tree.poll() is None, "no shell may be signalled while an agent is alive"
        events.append(f"sleep:{session_uuid}")
        with closing(a.conn()) as conn:
            conn.execute("UPDATE sessions SET lifecycle = 'stopped' WHERE session_uuid = ?", (session_uuid,))
            conn.commit()

    async def never(*args: Any) -> None:
        raise AssertionError("no Swarm body is live in this project")

    async def wake(session_uuid: str) -> None:
        events.append(f"wake:{session_uuid}")

    hooks = live.LiveHooks(session=session_move.Hooks(find=find, sleep=sleep, wake=wake, hide=never, account_key=lambda u: None, background_members=background_members, stop_members=stop_members),
                           sleep_agent=never, wake_agent=never)
    env = dataclasses.replace(env_mod.source_env(), find_live=find)
    try:
        blocked = asyncio.run(plan.plan_project(env, project, "iid-b", apply.guarded(link(a, b))))
        assert blocked.blocking == ["agents_ready"] and any("kestrel is running; the move will not start until it stops or you tick stop running agents now" in c["detail"] for c in blocked.checks)
        made = asyncio.run(plan.plan_project(env, project, "iid-b", apply.guarded(link(a, b)), stop_running=True))
        by_name = {c["name"]: c for c in made.checks}
        assert not made.blocking and by_name["live_agents"]["detail"] == "2 agents will stop here and continue on studio; 1 background shell will be stopped", made.view()

        state["mario_ends"] = False
        with pytest.raises(plan.MigrateError) as refused:
            asyncio.run(live.migrate(env, hooks, link(a, b), [made], kind="project", company_uid=None, op_id="live-op-fail", wait_seconds=0.4, settle=0.02, poll=0.005))
        assert refused.value.code == "turn_not_ended" and "kestrel" in refused.value.detail and "still working" in refused.value.detail, refused.value.detail
        assert events == [] and tree.poll() is None and a.project(uid)["pack_state"] == "home" and b.project(uid) is None
        with closing(a.conn()) as conn:
            failed = conn.execute("SELECT state, error_code FROM pack_migrations WHERE id = 'live-op-fail'").fetchone()
        assert tuple(failed) == ("failed", "turn_not_ended")

        state.update(mario_ends=True, mario_finds=0)
        wakes: list = []
        peer = link(a, b)

        async def spy(method: str, path: str, **kw: Any):
            if path.endswith("/wake"):
                wakes.append((method, path))
                return (409, {"detail": "this session is not asleep, so there is nothing to wake"}) if "sess-mario" in path else (200, {"status": "started"})
            return await peer(method, path, **kw)

        flipped = asyncio.run(live.migrate(env, hooks, spy, [made], kind="project", company_uid=None, op_id="live-op-ok", wait_seconds=10, settle=0.02, poll=0.005))
        assert events[0] == "measure_shells" and events[-1] == "stop_shells" and sorted(events[1:-1]) == ["sleep:sess-luigi", "sleep:sess-mario"], events
        assert flipped["machine"] == "studio" and a.project(uid)["pack_state"] == "moved_away" and b.project(uid)["pack_state"] == "home"
        assert tree.poll() is not None, "the throwaway shell tree is gone"
        with closing(b.conn()) as conn:
            assert sorted(r["lifecycle"] for r in conn.execute("SELECT lifecycle FROM sessions WHERE session_uuid IN ('sess-luigi', 'sess-mario')")) == ["stopped", "stopped"]
        with closing(a.conn()) as conn:
            row = conn.execute("SELECT state, step, detail_json FROM pack_migrations WHERE id = 'live-op-ok'").fetchone()
        assert (row["state"], row["step"]) == ("flipped", "flip") and '"live": 2' in row["detail_json"]
        assert sorted(wakes) == [("POST", "/sessions/sess-luigi/wake"), ("POST", "/sessions/sess-mario/wake")], wakes
        detail = json.loads(row["detail_json"])
        assert detail["woken"] == 1 and detail["wake_failed"] == [{"name": "kestrel", "reason": "this session is not asleep, so there is nothing to wake"}], detail
    finally:
        if tree.poll() is None:
            os.killpg(tree.pid, signal.SIGKILL)
            tree.wait()
