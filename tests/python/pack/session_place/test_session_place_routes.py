
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi import FastAPI

from src.api import session_place_routes as routes
from src.api.auth import require_auth
from src.core.federation.peer_client import PeerUnreachable
from src.core.pack.jobs import boot, place, policy as policy_mod
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, JobError
from src.core.pack.placement import rule
from src.core.pack.reserve.holds import HOLDS
from src.core.pack.session_place import create as create_mod, decide as decide_mod
from src.core.pack.session_place.types import CAP_SESSION_PLACE, PlaceRequest, SessionPlacement, Starter
from src.core.pack.session_place.wire import PeerCreateAnswer
from src.models import CreateSessionRequest

UID = "p1x23456"
A, B, C = "iid-a", "iid-b", "iid-c"
HEAD = "a" * 40
CAPS = [CAP_JOBS, CAP_SESSION_PLACE]
RID = "c" * 32


def snap(load1: float) -> Dict[str, Any]:
    return {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": True},
            "can": {"tools": {"claude": True}, "xcode": False, "brew": False}}


def make_view(self_load: float, peers: Dict[str, str]) -> place.PlaceView:
    me = rule.MachineInput(A, "nostromo", snap(self_load), True, True, True, True, 0)
    ps = [rule.MachineInput(iid, label, snap(0.5), True, False, False, True, None) for iid, label in peers.items()]
    return place.PlaceView(me, ps, {p.install_id: list(CAPS) for p in ps}, A)


class World:

    def __init__(self, store: JobStore) -> None:
        self.store, self.view = store, make_view(1.0, {})
        self.posts: List[Any] = []
        self.script: Dict[str, Any] = {}
        self.local: List[Any] = []
        self.dirty = 3
        self.carried: List[str] = []


@pytest.fixture()
def world(tmp_path: Path, monkeypatch) -> World:
    HOLDS._entries.clear()
    w = World(JobStore(tmp_path / "state"))
    policy_mod.set_auto(w.store, UID, True)
    monkeypatch.setitem(boot._built, "engine", SimpleNamespace(store=w.store, _view_for=lambda root, uid: w.view))
    monkeypatch.setattr(decide_mod, "_project_of", lambda req, eng: (UID, "app", "/w/app"))
    monkeypatch.setattr(decide_mod, "_copies", lambda eng, uid: {B: "/w/app-b", C: "/w/app-c"})
    monkeypatch.setattr(create_mod, "_project", lambda name: {"uid": UID, "display_name": name, "root": "/w/app"})
    monkeypatch.setattr(create_mod, "_git_facts", lambda root: (HEAD, "main", w.dirty))
    monkeypatch.setattr(create_mod, "_peer", lambda iid: SimpleNamespace(key=f"peer-{iid[-1]}", label=iid, peer_install_id=iid))

    async def carry(project: Dict[str, Any], install_id: str, label: str) -> Dict[str, Any]:
        w.carried.append(install_id)
        return {"machine": label, "sent": True}

    async def post(install_id: str, label: str, body: Any) -> PeerCreateAnswer:
        w.posts.append((install_id, body))
        got = w.script.get(install_id)
        if isinstance(got, Exception):
            raise got
        return got or PeerCreateAnswer(session_id="ses_far", session_uuid="u-far", tmux_name=f"carnivore_{install_id[-1]}", working_dir="/w/app-b",
                                       account_label="work", account_how="relay", profile_used="default")

    async def local(request: Any, body: CreateSessionRequest) -> Dict[str, Any]:
        w.local.append(body)
        return {"id": "ses_local1", "working_dir": body.working_dir}

    monkeypatch.setattr(create_mod, "_carry", carry)
    monkeypatch.setattr(create_mod, "_post", post)
    monkeypatch.setattr(routes, "create_session_with_extra", local)
    yield w
    HOLDS._entries.clear()


def call(path: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_auth] = lambda: None

    async def go() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await client.post(path, json=body, headers=headers)

    return asyncio.run(go())


BODY = {"working_dir": "/w/app", "agent_type": "claude"}


def test_default_stays_local_when_this_computer_has_room(world):
    world.view = make_view(1.0, {B: "tower"})
    got = call("/sessions/auto", BODY)
    assert got.status_code == 201
    out = got.json()
    assert out["session"]["id"] == "ses_local1" and out["placement"]["decision"] == "here"
    assert out["placement"]["reason"].startswith("this computer has room")
    assert len(world.local) == 1 and world.local[0].working_dir == "/w/app" and not world.posts and not world.carried


def test_a_pegged_computer_sends_it_to_the_copy_under_its_wire_id_and_says_what_stayed(world):
    world.view = make_view(9.8, {B: "tower"})
    out = call("/sessions/auto", {**BODY, "label": "trader"}).json()
    assert not world.local and world.carried == [B]
    assert out["session"]["id"] == "remote:peer-b:carnivore_b" and out["session"]["host_label"] == "iid-b"
    block = out["placement"]
    assert (block["decision"], block["computer"], block["label"], block["code"]) == ("remote", B, "tower", None)
    assert block["left_behind"] == 3 and block["work_lives"] == "tower keeps this session's work until it pushes or you move it back"
    assert block["started_at"] == {"head": HEAD[:12], "branch": "main"} and block["account"] == "work" and block["account_how"] == "relay"
    sent = world.posts[0][1]
    assert (sent.home_head, sent.branch, sent.family, sent.posture, sent.label, sent.account_key) == (HEAD, "main", "claude", "skip_all", "trader", None)
    row = world.store.placement_get(block["request_id"])
    assert row["decision"] == "remote" and row["session_id"] == out["session"]["id"] and row["starter_kind"] == "owner"


def test_one_refusal_replaces_once_on_another_computer(world):
    world.view = make_view(9.8, {B: "tower", C: "mini"})
    world.script[B] = JobError("copy_not_ready", "tower's copy has changes of its own", 409)
    out = call("/sessions/auto", BODY).json()
    assert [p[0] for p in world.posts] == [B, C] and not world.local
    assert out["placement"]["computer"] == C and out["session"]["id"] == "remote:peer-c:carnivore_c"
    assert any("tower refused" in r for r in out["placement"]["reasons"])


def test_a_refusal_with_nobody_else_answers_here_with_both_reasons(world):
    world.view = make_view(9.8, {B: "tower"})
    world.script[B] = JobError("pack_restricted", "tower does not take work", 403)
    out = call("/sessions/auto", BODY).json()
    block = out["placement"]
    assert [p[0] for p in world.posts] == [B] and len(world.local) == 1 and out["session"]["id"] == "ses_local1"
    assert block["decision"] == "here" and "tower refused (tower does not take work)" in block["reason"] and len(block["reason"]) <= 160
    assert len(block["reasons"]) >= 3 and "tower refused: tower does not take work" in block["reasons"]


def test_two_refusals_end_here_and_ask_no_third_computer(world):
    world.view = make_view(9.8, {B: "tower", C: "mini"})
    world.script[B] = JobError("copy_not_ready", "behind", 409)
    world.script[C] = JobError("pegged", "busy", 409)
    block = call("/sessions/auto", BODY).json()["placement"]
    assert [p[0] for p in world.posts] == [B, C] and len(world.local) == 1 and block["decision"] == "here"
    assert "mini refused (busy)" in block["reason"]


def test_an_approved_computer_that_refuses_starts_here_and_no_other_is_asked(world, monkeypatch):
    world.view = make_view(9.8, {B: "tower", C: "mini"})
    world.script[B] = JobError("copy_in_use", "tower's copy is in use and behind", 409)

    async def never(*a: Any, **k: Any) -> None:
        raise AssertionError("an approved placement is never re-decided")

    monkeypatch.setattr(decide_mod, "decide", never)
    approved = SessionPlacement("remote", "this computer is pegged (9.8 of 10 cores busy)", B, "tower", "/w/app-b", project_uid=UID, project_name="app")
    starter = Starter(kind="agent", account_key="work-1", posture="accept_edits", model="claude-opus-4-1")
    body = CreateSessionRequest(working_dir="/w/app")

    async def local(b: Any) -> Dict[str, Any]:
        world.local.append(b)
        return {"id": "ses_local1"}

    got = asyncio.run(create_mod.create_placed(None, PlaceRequest(working_dir="/w/app"), starter, body, local_create=local, approved=approved))
    sent = world.posts[0][1]
    assert (world.posts[0][0], sent.account_key, sent.posture, sent.model) == (B, "work-1", "accept_edits", "claude-opus-4-1")
    assert [p[0] for p in world.posts] == [B] and len(world.local) == 1 and got.placement["decision"] == "here"
    assert got.placement["reasons"][0] == approved.reason and "copy is in use" in got.placement["reasons"][1]


def test_the_same_request_id_answers_one_session(world):
    world.view = make_view(9.8, {B: "tower"})
    first = call("/sessions/auto", {**BODY, "request_id": RID}).json()
    second = call("/sessions/auto", {**BODY, "request_id": RID}).json()
    assert len(world.posts) == 1 and not world.local
    assert second["session"]["id"] == first["session"]["id"] and second["placement"]["replayed"] is True


def test_a_timeout_is_retried_once_with_the_same_request_id(monkeypatch):
    sent: List[Any] = []

    class Client:
        async def request(self, method: str, path: str, *, json: Any = None, content: Any = None, headers: Any = None, timeout: Any = None):
            sent.append(json)
            if len(sent) == 1:
                raise asyncio.TimeoutError()
            answer = {"session_id": "ses_far", "tmux_name": "carnivore_b", "working_dir": "/w/app-b"}
            return SimpleNamespace(status_code=200, json=lambda: answer)

    monkeypatch.setattr(create_mod.peer_links, "LINKS", SimpleNamespace(client=lambda iid: Client()))
    body = create_mod.PeerCreateBody(request_id=RID, project_uid=UID, home_head=HEAD, branch="main")
    got = asyncio.run(create_mod._post(B, "tower", body))
    assert got.tmux_name == "carnivore_b" and len(sent) == 2 and sent[0]["request_id"] == sent[1]["request_id"] == RID
    sent.clear()

    class Dead(Client):
        async def request(self, *a: Any, **k: Any):
            sent.append(1)
            raise PeerUnreachable("closed", hard=True)

    monkeypatch.setattr(create_mod.peer_links, "LINKS", SimpleNamespace(client=lambda iid: Dead()))
    with pytest.raises(JobError) as gone:
        asyncio.run(create_mod._post(B, "tower", body))
    assert gone.value.code == "unreachable" and len(sent) == 1


def test_a_need_nobody_meets_is_a_409_and_creates_nothing(world):
    world.view = make_view(1.0, {B: "tower"})
    got = call("/sessions/auto", {**BODY, "needs": ["xcode"]})
    assert got.status_code == 409
    detail = got.json()["detail"]
    assert detail["code"] == "requirement_unmet" and detail["placement"]["decision"] == "refused" and "xcode" in detail["placement"]["reason"]
    assert not world.local and not world.posts and not world.carried


def test_what_another_computer_says_is_capped_and_stripped(world):
    world.view = make_view(9.8, {B: "tower"})
    world.script[B] = PeerCreateAnswer(session_id="s", tmux_name="carnivore_b", working_dir="/w/\x1b[31mapp" + "x" * 300, account_label="a\x00b" * 100,
                                       copy_note="note\x07" + "n" * 300)
    block = call("/sessions/auto", BODY).json()
    assert all(ord(ch) >= 32 for ch in block["session"]["working_dir"]) and len(block["session"]["working_dir"]) <= 160
    assert len(block["placement"]["account"]) <= 160 and "\x00" not in block["placement"]["account"]
    assert len(block["placement"]["note"]) <= 160 and "\x07" not in block["placement"]["note"]
    assert create_mod.clean("a\x1b[2Jb") == "a [2Jb" and len(create_mod.clean("y" * 500)) == 160
    refusal = create_mod._refusal(409, {"detail": {"code": "Bad Code;rm", "detail": "no\x00pe"}})
    assert refusal.code == "http_409" and refusal.detail == "no pe"


def test_a_session_name_that_could_not_be_a_name_is_never_used(monkeypatch):
    class Client:
        async def request(self, *a: Any, **k: Any):
            answer = {"session_id": "s", "tmux_name": "bad name;rm -rf"}
            return SimpleNamespace(status_code=200, json=lambda: answer)

    monkeypatch.setattr(create_mod.peer_links, "LINKS", SimpleNamespace(client=lambda iid: Client()))
    body = create_mod.PeerCreateBody(request_id=RID, project_uid=UID, home_head=HEAD, branch="main")
    with pytest.raises(JobError) as bad:
        asyncio.run(create_mod._post(B, "tower", body))
    assert bad.value.code == "bad_answer"


def test_a_field_the_far_create_cannot_carry_stays_here_with_its_reason(world):
    world.view = make_view(9.8, {B: "tower"})
    for extra, words in (({"worktree": {"branch": "x"}}, "a new worktree"), ({"opening_prompt": "do the thing please"}, "an opening prompt"),
                         ({"account_id": "acct-1"}, "a chosen account")):
        world.local.clear()
        block = call("/sessions/auto", {**BODY, **extra}).json()["placement"]
        assert block["decision"] == "here" and words in block["reason"] and len(world.local) == 1
    assert not world.posts


def test_posture_never_rises():
    assert create_mod._posture(Starter(posture="skip_all")) == "skip_all"
    assert create_mod._posture(Starter(posture="bypassPermissions")) == "unknown"
    assert create_mod._posture(Starter()) == "unknown"


def test_explain_answers_the_placement_and_writes_nothing(world):
    world.view = make_view(9.8, {B: "tower"})
    got = call("/pack/session-placement/explain", BODY).json()
    assert set(got) == {"placement"} and got["placement"]["decision"] == "remote" and got["placement"]["computer"] == B
    assert not world.local and not world.posts and not world.carried and world.store.placement_list(UID) == []
    assert call("/pack/session-placement/explain", {**BODY, "needs": ["x"] * 9}).status_code == 422
    assert call("/pack/session-placement/explain", {**BODY, "request_id": "short"}).status_code == 422


def test_an_api_key_is_refused_on_the_create_route_but_may_ask_the_dry_run(world, monkeypatch):
    monkeypatch.setattr(routes, "is_api_key", lambda token: True)
    headers = {"Authorization": "Bearer cck_test"}
    assert call("/sessions/auto", BODY, headers).status_code == 403
    assert call("/pack/session-placement/explain", BODY, headers).status_code == 200
    assert not world.local


def test_reading_the_home_changes_nothing_in_its_git_folder_and_runs_none_of_its_config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (repo / "t.txt").write_text("same")
    marker = tmp_path / "PWNED"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    hook.chmod(0o755)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "one"], ["config", "core.fsmonitor", str(hook)]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)
    time.sleep(1.1)
    (repo / "t.txt").write_text("same")
    (repo / "a.txt").write_text("a")
    (repo / "t.txt").touch()

    def tree() -> Dict[str, Any]:
        return {str(p.relative_to(repo)): (p.stat().st_size, p.stat().st_mtime_ns) for p in (repo / ".git").rglob("*") if p.is_file() and p.name != "config"}

    before = tree()
    head, branch, dirty = create_mod._git_facts(str(repo))
    assert len(head) == 40 and branch == "main" and dirty == 1
    assert tree() == before and not marker.exists()
    with pytest.raises(JobError) as none:
        create_mod._git_facts(str(tmp_path))
    assert none.value.code == "not_a_repo"


def test_a_here_create_leaves_its_one_history_row(world):
    got = call("/sessions/auto", BODY).json()
    row = world.store.placement_get(got["placement"]["request_id"])
    assert row is not None and row["decision"] == "here"


def test_an_approved_card_is_checked_again_against_the_owners_rules_now(world):
    world.view = make_view(1.0, {B: "tower"})
    policy_mod.set_lists(world.store, UID, never_use=[B])
    approved = SessionPlacement("remote", "this computer is pegged", B, "tower", "/w/app-b", project_uid=UID, project_name="app")

    async def local(body: Any) -> Any:
        return {"id": "ses_local1", "working_dir": body.working_dir}

    got = asyncio.run(create_mod.create_placed(None, PlaceRequest(working_dir="/w/app"), Starter(), CreateSessionRequest(working_dir="/w/app"),
                                               local_create=local, approved=approved))
    assert got.placement["decision"] == "here" and "never use" in got.placement["reason"] and not world.carried and not world.posts
    policy_mod.set_lists(world.store, UID, never_use=[])
    policy_mod.set_auto(world.store, UID, False)
    got = asyncio.run(create_mod.create_placed(None, PlaceRequest(working_dir="/w/app"), Starter(), CreateSessionRequest(working_dir="/w/app"),
                                               local_create=local, approved=approved, request_id="d" * 32))
    assert got.placement["decision"] == "here" and not world.carried


def test_a_session_in_a_worktree_of_the_project_stays_here(world, tmp_path):
    world.view = make_view(9.8, {B: "tower"})
    root = tmp_path / "app"
    tree = root / "wt"
    tree.mkdir(parents=True)
    (tree / ".git").write_text("gitdir: /elsewhere")
    import src.core.pack.session_place.create as c

    world_project = {"uid": UID, "display_name": "app", "root": str(root)}
    world.project = world_project
    got = asyncio.run(_run_with_root(world, str(tree), str(root), c))
    assert got.placement["decision"] == "here" and "worktree" in got.placement["reason"] and not world.carried


async def _run_with_root(world, folder: str, root: str, c) -> Any:
    async def local(body: Any) -> Any:
        return {"id": "ses_local1", "working_dir": body.working_dir}

    old = c._project
    c._project = lambda name: {"uid": UID, "display_name": name, "root": root}
    try:
        return await c.create_placed(None, PlaceRequest(working_dir=folder), Starter(), CreateSessionRequest(working_dir=folder), local_create=local)
    finally:
        c._project = old


def test_a_wire_name_that_is_too_long_starts_here_before_anything_is_carried(world):
    world.view = make_view(9.8, {B: "tower"})

    async def local(body: Any) -> Any:
        return {"id": "ses_local1", "working_dir": body.working_dir}

    got = asyncio.run(create_mod.create_placed(None, PlaceRequest(working_dir="/w/app", profile_name="p" * 150), Starter(),
                                               CreateSessionRequest(working_dir="/w/app"), local_create=local))
    assert got.placement["decision"] == "here" and not world.carried and not world.posts


def test_a_profile_of_another_harness_stays_here(world, monkeypatch):
    from src.config import settings
    from src.config.launch_profiles import LaunchProfile

    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: [LaunchProfile.model_validate({"id": "hm-fast", "harness": "hermes", "label": "h", "custom_command": {"script": 'hermes "$@"'}}),
                                                                  LaunchProfile.model_validate({"id": "cdx-fast", "harness": "codex", "label": "c"})])
    world.view = make_view(9.8, {B: "tower"})
    out = call("/sessions/auto", {**BODY, "agent_type": "hm-fast"}).json()
    assert out["placement"]["decision"] == "here" and "another kind" in out["placement"]["reason"] and len(world.local) == 1
    out = call("/pack/session-placement/explain", {**BODY, "agent_type": "cdx-fast"}).json()
    assert "another kind" not in out["placement"]["reason"]
    req = routes.place_request(routes.AutoCreateBody(working_dir="/w/app", agent_type="cdx-fast"))
    assert (req.family, req.profile_name) == ("codex", "cdx-fast")


def _profiles(monkeypatch, *rows):
    from src.config import settings
    from src.config.launch_profiles import LaunchProfile

    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: [LaunchProfile.model_validate(r) for r in rows])


def test_an_owner_start_carries_the_posture_this_computer_would_launch_with(world, monkeypatch):
    world.view = make_view(9.8, {B: "tower"})
    _profiles(monkeypatch)
    call("/sessions/auto", BODY)
    assert world.posts[-1][1].posture == "skip_all"
    _profiles(monkeypatch, {"id": "cld-ask", "harness": "claude", "label": "a", "permissions": "ask"})
    call("/sessions/auto", {**BODY, "agent_type": "cld-ask"})
    assert world.posts[-1][1].posture == "ask"


def test_a_posture_field_from_the_browser_is_ignored(world, monkeypatch):
    world.view = make_view(9.8, {B: "tower"})
    _profiles(monkeypatch, {"id": "cld-ask", "harness": "claude", "label": "a", "permissions": "ask", "default": True})
    call("/sessions/auto", {**BODY, "posture": "skip_all"})
    assert world.posts[-1][1].posture == "ask"
