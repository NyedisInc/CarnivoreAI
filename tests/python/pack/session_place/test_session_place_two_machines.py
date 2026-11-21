
from __future__ import annotations

import asyncio
import os
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.config.launch_profiles import LaunchProfile  # noqa: E402
from src.api import federation_pack_session_place_routes as routes  # noqa: E402
from src.api import peer_auth  # noqa: E402
from src.core.crosstalk import spawn  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.mcp import write_tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.core.pack.identity import replicas  # noqa: E402
from src.core.pack.jobs import agent_launch, boot, place, policy as policy_mod  # noqa: E402
from src.core.pack.jobs.agent_account import AccountPick  # noqa: E402
from src.core.pack.jobs.agent_host import AgentDeps  # noqa: E402
from src.core.pack.jobs.host import Host  # noqa: E402
from src.core.pack.jobs.store import JobStore  # noqa: E402
from src.core.pack.jobs.types import CAP_JOBS  # noqa: E402
from src.core.pack.machines.restrictions import Restrictions  # noqa: E402
from src.core.pack.placement import rule  # noqa: E402
from src.core.pack.reserve.holds import HOLDS  # noqa: E402
from src.core.pack.session_place import create as create_mod, decide as decide_mod, host as session_host  # noqa: E402
from src.core.pack.session_place.types import CAP_SESSION_PLACE, PlaceRequest, Starter  # noqa: E402
from src.core.pack.session_place.wire import CREATE_PATH, PeerCreateAnswer  # noqa: E402
from src.models import CreateSessionRequest  # noqa: E402

A, B, UID = "iid-a", "iid-b", "p1x23456"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=ENV, check=True).stdout.strip()


def snap(load1: float, *, may_host: bool = True) -> Dict[str, Any]:
    return {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": may_host},
            "can": {"tools": {"claude": True}, "xcode": False, "brew": False}}


def view(a_load: float, *, b_may_host: bool = True) -> place.PlaceView:
    me = rule.MachineInput(A, "nostromo", snap(a_load), True, True, True, True, 0)
    other = rule.MachineInput(B, "tower", snap(0.5, may_host=b_may_host), True, False, False, True, None)
    return place.PlaceView(me, [other], {B: [CAP_JOBS, CAP_SESSION_PLACE]}, A)


class World:

    def __init__(self, tmp: Path, monkeypatch: Any) -> None:
        self.tmp, self.view = tmp, view(9.8)
        self.home, self.copy = tmp / "home", tmp / "copy"
        self.home.mkdir()
        git(self.home, "init", "-q", "-b", "main")
        (self.home / "a.txt").write_text("one")
        git(self.home, "add", "a.txt")
        git(self.home, "commit", "-q", "-m", "one")
        subprocess.run(["git", "clone", "-q", str(self.home), str(self.copy)], check=True, env=ENV, capture_output=True)
        (self.home / "b.txt").write_text("two")
        git(self.home, "add", "b.txt")
        git(self.home, "commit", "-q", "-m", "two")
        self.head = git(self.home, "rev-parse", "HEAD")
        (self.home / "wip.txt").write_text("not committed")
        self.store = JobStore(tmp / "astate")
        policy_mod.set_auto(self.store, UID, True)
        self.state = tmp / "bstate"
        self.state.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        with closing(connect(db_path_for(self.state), create=False)) as conn:
            replicas.accept_replica(conn, home_install_id=A, project_uid=UID, name="app", root=str(self.copy))
        self.restrictions, self.created, self.local = Restrictions(), [], []
        self.host = Host(state_dir=self.state, jobs_root=tmp / "bjobs", install_id=B, open_db=lambda: connect(db_path_for(self.state), create=False),
                         restrictions=lambda: self.restrictions, live_agents=lambda: 0, admit=lambda work: None)
        self.host.agent.bind(self.deps())
        app = FastAPI()
        app.include_router(routes.router, prefix="/api/v1")
        app.state.pack_jobs_host = self.host
        config = tmp / "config.json"
        config.write_text("{}")
        app.state.session_place_seams = session_host.Seams(live_folders=self.no_live, config_path=lambda: config, profiles=lambda: [LaunchProfile.model_validate({"id": "claude-ask", "harness": "claude", "label": "ask", "permissions": "ask", "default": True})])
        principal = peer_auth.Principal("peer", SimpleNamespace(peer_install_id=A))
        app.dependency_overrides[routes._require_replica] = lambda: principal
        self.client = TestClient(app)
        monkeypatch.setitem(boot._built, "engine", SimpleNamespace(store=self.store, _view_for=lambda root, uid: self.view))
        monkeypatch.setattr(decide_mod, "_project_of", lambda req, eng: (UID, "app", str(self.home)))
        monkeypatch.setattr(decide_mod, "_copies", lambda eng, uid: {B: str(self.copy)})
        monkeypatch.setattr(create_mod, "_project", lambda name: {"uid": UID, "display_name": name, "root": str(self.home)})
        monkeypatch.setattr(create_mod, "_peer", lambda iid: SimpleNamespace(key="peer-b", label="tower", peer_install_id=iid))
        monkeypatch.setattr(create_mod, "_carry", self.carry)
        monkeypatch.setattr(create_mod, "_post", self.post)

    async def no_live(self, app: Any) -> List[str]:
        return []

    def deps(self) -> AgentDeps:
        async def create(plan: Any, session_id: str, label: str, working_dir: str) -> agent_launch.WorkerRef:
            self.created.append({"dir": working_dir, "head": git(self.copy, "rev-parse", "HEAD"), "plan": plan})
            return agent_launch.WorkerRef(session_id, "u-far", f"carnivore_{session_id}", 1234)

        async def nothing(*a: Any, **k: Any) -> Any:
            return (None, None)

        async def unlisted(session_id: str) -> bool:
            return False

        return AgentDeps(create, nothing, lambda sid: None, nothing, unlisted, nothing, lambda f, k, c: AccountPick("work", {}, "work", "same"),
                         harness_present=lambda family: True)

    async def carry(self, project: Dict[str, Any], install_id: str, label: str) -> Dict[str, Any]:
        git(self.copy, "fetch", "-q", str(self.home), "main:refs/carnivore/iid-a/heads/main")
        return {"machine": label, "sent": True}

    async def post(self, install_id: str, label: str, body: Any) -> PeerCreateAnswer:
        reply = await asyncio.to_thread(self.client.post, "/api/v1" + CREATE_PATH, json=body.model_dump(exclude_none=True))
        if reply.status_code != 200:
            raise create_mod._refusal(reply.status_code, reply.json())  # noqa: SLF001
        return PeerCreateAnswer.model_validate(reply.json())

    async def local_create(self, body: Any) -> Any:
        self.local.append(body)
        return SimpleNamespace(id="ses_local1", working_dir=body.working_dir)

    def auto(self, request_id: str = "d" * 32, **body: Any) -> Any:
        req = PlaceRequest(working_dir=str(self.home), family="claude")
        create = CreateSessionRequest(working_dir=str(self.home), agent_type="claude", **body)
        return asyncio.run(create_mod.create_placed(SimpleNamespace(), req, Starter(), create, local_create=self.local_create, request_id=request_id))


@pytest.fixture()
def world(tmp_path: Path, monkeypatch) -> World:
    HOLDS._entries.clear()
    yield World(tmp_path, monkeypatch)
    HOLDS._entries.clear()


def test_pegged_home_starts_the_session_on_b_at_a_head_and_names_what_stayed(world: World) -> None:
    got = world.auto()
    block = got.placement
    assert (block["decision"], block["computer"], block["label"]) == ("remote", B, "tower") and not world.local
    assert got.session["id"] == "remote:peer-b:" + got.session["tmux_session"] and got.session["host_label"] == "tower"
    assert len(world.created) == 1 and world.created[0]["dir"] == os.path.realpath(world.copy) and world.created[0]["head"] == world.head
    assert not (world.copy / "wip.txt").exists() and (world.copy / "b.txt").read_text() == "two"
    assert block["left_behind"] == 1 and block["work_lives"] == "tower keeps this session's work until it pushes or you move it back"
    assert block["started_at"]["head"] == world.head[:12] and (world.home / "wip.txt").read_text() == "not committed"
    assert world.host.store.host_place_get("d" * 32) is not None


def test_default_placement_stays_on_a_when_a_has_room(world: World) -> None:
    world.view = view(1.0)
    got = world.auto()
    assert got.placement["decision"] == "here" and len(world.local) == 1 and not world.created
    assert git(world.copy, "rev-parse", "HEAD") != world.head


def test_b_with_takes_work_off_keeps_the_session_on_a_with_the_reason(world: World) -> None:
    world.view = view(9.8, b_may_host=False)
    got = world.auto()
    assert got.placement["decision"] == "here" and got.placement["reason"] and len(world.local) == 1 and not world.created


def test_b_switch_flipped_after_placement_is_refused_by_b_and_the_session_starts_here(world: World) -> None:
    world.restrictions = Restrictions(may_host_agents=False)
    got = world.auto()
    assert got.placement["decision"] == "here" and "tower refused" in got.placement["reason"]
    assert len(world.local) == 1 and not world.created and git(world.copy, "rev-parse", "HEAD") != world.head


def test_a_dirty_behind_copy_is_not_moved_and_the_session_starts_on_a(world: World) -> None:
    (world.copy / "a.txt").write_text("edited on b")
    before = git(world.copy, "rev-parse", "HEAD")
    got = world.auto()
    assert got.placement["decision"] == "here" and "tower refused" in got.placement["reason"] and len(world.local) == 1 and not world.created
    assert git(world.copy, "rev-parse", "HEAD") == before and (world.copy / "a.txt").read_text() == "edited on b"


def test_the_same_request_id_twice_makes_one_session(world: World) -> None:
    first = world.auto()
    HOLDS._entries.clear()
    second = world.auto()
    assert len(world.created) == 1 and second.placement["replayed"] is True
    assert second.session["id"] == first.session["id"] and not world.local


def test_h6_forwarded_create_with_a_host_key_never_enters_auto(world: World) -> None:
    got = world.auto(host_key="peer-b")
    assert got.placement["decision"] == "here" and "chosen by hand" in got.placement["reason"] and not world.created


def test_h6_session_create_with_peer_sends_the_same_body_and_no_placement_fields(world: World, monkeypatch) -> None:
    from src.core.mcp import beast_mode, federated

    sent: List[Dict[str, Any]] = []

    async def find_peer(name: str) -> Any:
        return SimpleNamespace(key="peer-b", label="tower", peer_install_id=B)

    async def create(peer: Any, body: Dict[str, Any]) -> Dict[str, Any]:
        sent.append(body)
        return {"id": "remote:peer-b:x", "working_dir": "/far"}

    async def park(manager, caller, tid, tmux, action, summary, shown, run, *rest, **kw) -> dict:
        return await run(True)

    async def never(*a: Any, **k: Any) -> None:
        raise AssertionError("a peer create never asks the placement")

    manager = SimpleNamespace(live_ids_now=lambda: asyncio.sleep(0, result=set()))
    monkeypatch.setattr(federated, "find_peer", find_peer)
    monkeypatch.setattr(federated, "create", create)
    monkeypatch.setattr(write_tools, "park", park)
    monkeypatch.setattr(beast_mode, "approval_skip", lambda action: False)
    monkeypatch.setattr(decide_mod, "decide", never)
    write_tools._created.clear()
    write_tools._reserved.clear()
    asyncio.run(write_tools.session_create(manager, AgentCaller("ses_c", "cloude_c", "ses_c"), {"peer": "tower", "working_dir": "/far", "agent_type": "claude", "name": "n"}))
    assert sent == [{"working_dir": "/far", "agent_type": "claude", "label": "n"}]
    write_tools._created.clear()


def test_h6_agent_spawn_with_peer_payload_carries_no_placement_fields() -> None:
    body = spawn.SpawnRequest.model_validate({"provider": "claude", "task": "t", "peer": "tower", "working_dir": "/far"})
    from src.core.crosstalk import spawn_remote

    payload = spawn_remote.peer_spawn_payload(body, False)
    assert set(payload) == {"provider", "task", "working_dir", "report_back", "worktree", "beast"}
    assert "placement" not in payload and "needs" not in payload and "peer" not in payload and payload["working_dir"] == "/far"
