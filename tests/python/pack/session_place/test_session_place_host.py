
from __future__ import annotations

import json
import os
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_session_place_routes as routes  # noqa: E402
from src.api import peer_auth  # noqa: E402
from src.config.launch_profiles import LaunchProfile  # noqa: E402
from src.core.account_switch import session_pin  # noqa: E402
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.pack.identity import replicas  # noqa: E402
from src.core.pack.jobs import agent_launch, host_admit  # noqa: E402
from src.core.pack.jobs.agent_account import AccountPick  # noqa: E402
from src.core.pack.jobs.agent_host import AgentDeps  # noqa: E402
from src.core.pack.jobs.host import Host  # noqa: E402
from src.core.pack.jobs.types import JobError  # noqa: E402
from src.core.pack.machines.restrictions import Restrictions  # noqa: E402
from src.core.pack.reserve.holds import HOLDS  # noqa: E402
from src.core.pack.session_place import copy_ready, host as session_host  # noqa: E402
from src.core.pack.session_place.wire import CREATE_PATH, PeerCreateBody  # noqa: E402

HOME = "iid-a"
REQ = "a" * 32
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=ENV, check=True).stdout.strip()


def commit(repo: Path, name: str, text: str = "x") -> str:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


class Sim:

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.state = tmp / "state"
        self.state.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        self.home_repo, self.copy = tmp / "home", tmp / "copy"
        self.home_repo.mkdir()
        git(self.home_repo, "init", "-q", "-b", "main")
        self.h1 = commit(self.home_repo, "a.txt", "one")
        subprocess.run(["git", "clone", "-q", str(self.home_repo), str(self.copy)], check=True, env=ENV, capture_output=True)
        self.h2 = commit(self.home_repo, "b.txt", "two")
        self.restrictions = Restrictions()
        self.created: List[Dict[str, Any]] = []
        self.accounts: Any = AccountPick("work", {}, "work", "same")
        self.live: List[str] = []
        self.profiles: List[Any] = [profile("claude-ask", "ask", default=True), profile("codex-ask", "ask", "codex", default=True)]
        self.uuid = "u-0001"
        self.config = tmp / "config.json"
        self.config.write_text("{}")
        with closing(connect(db_path_for(self.state), create=False)) as conn:
            replicas.accept_replica(conn, home_install_id=HOME, project_uid="p1x23456", name="app", root=str(self.copy))
        self.host = Host(state_dir=self.state, jobs_root=tmp / "jobs", install_id="iid-b", open_db=lambda: connect(db_path_for(self.state), create=False),
                         restrictions=lambda: self.restrictions, live_agents=lambda: 0, admit=lambda work: None)
        self.host.agent.bind(self.deps())
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/api/v1")
        self.app.state.pack_jobs_host = self.host
        self.app.state.session_place_seams = session_host.Seams(live_folders=self.live_folders, config_path=lambda: self.config, profiles=lambda: self.profiles)
        self.principal = peer_auth.Principal("peer", SimpleNamespace(peer_install_id=HOME))
        self.app.dependency_overrides[routes._require_replica] = lambda: self.principal
        self.client = TestClient(self.app)

    async def live_folders(self, app: Any) -> List[str]:
        return list(self.live)

    def deps(self) -> AgentDeps:
        async def create(plan: Any, session_id: str, label: str, working_dir: str) -> agent_launch.WorkerRef:
            self.created.append({"plan": plan, "session_id": session_id, "label": label, "dir": working_dir, "head": git(self.copy, "rev-parse", "HEAD")})
            return agent_launch.WorkerRef(session_id, self.uuid, f"carnivore_{session_id}", 1234)

        async def stop(*a: Any, **k: Any) -> None:
            pass

        async def none(*a: Any) -> None:
            pass

        async def listed(session_id: str) -> bool:
            return False

        def resolve(family: str, key: Optional[str], caller: Optional[str]) -> AccountPick:
            if isinstance(self.accounts, Exception):
                raise self.accounts
            return self.accounts

        async def conv(session_id: str) -> Any:
            return (None, None)

        return AgentDeps(create, stop, lambda sid: None, none, listed, conv, resolve, harness_present=lambda family: True)

    def fetch_carried(self) -> None:
        git(self.copy, "fetch", "-q", str(self.home_repo), "main:refs/carnivore/iid-a/heads/main")

    def body(self, **over: Any) -> Dict[str, Any]:
        return {"request_id": REQ, "project_uid": "p1x23456", "home_head": self.h2, "branch": "main", "family": "claude", "posture": "ask", **over}

    def post(self, **over: Any) -> Any:
        return self.client.post("/api" + "/v1" + CREATE_PATH, json=self.body(**over))


@pytest.fixture()
def sim(tmp_path: Path) -> Sim:
    HOLDS._entries.clear()
    s = Sim(tmp_path)
    s.fetch_carried()
    yield s
    HOLDS._entries.clear()


def profile(pid: str, perms: str, harness: str = "claude", default: bool = False, **extra: Any) -> LaunchProfile:
    return LaunchProfile.model_validate({"id": pid, "harness": harness, "label": pid, "permissions": perms, "default": default, **extra})


def resolved(sim: "Sim", n: int = 0) -> Any:
    plan = sim.created[n]["plan"]
    return resolve_launch(LaunchRequest(profiles=tuple(sim.profiles), agent_type=plan.agent_type, app_args=tuple(plan.extra_args)))


def code_of(reply: Any) -> str:
    return reply.json()["detail"]["code"]


def test_clean_behind_copy_fast_forwards(sim: Sim) -> None:
    reply = sim.post()
    assert reply.status_code == 200, reply.text
    assert git(sim.copy, "rev-parse", "HEAD") == sim.h2
    assert sim.created[0]["dir"] == os.path.realpath(sim.copy) and sim.created[0]["head"] == sim.h2
    assert "moved forward" in reply.json()["copy_note"] and reply.json()["working_dir"] == os.path.realpath(sim.copy)


@pytest.mark.parametrize("how", ["dirty", "diverged"])
def test_dirty_or_diverged_copy_refuses_and_writes_nothing(sim: Sim, how: str) -> None:
    if how == "dirty":
        (sim.copy / "a.txt").write_text("edited")
    else:
        commit(sim.copy, "own.txt")
    before = git(sim.copy, "rev-parse", "HEAD")
    reply = sim.post()
    assert (reply.status_code, code_of(reply)) == (409, "copy_not_ready")
    assert git(sim.copy, "rev-parse", "HEAD") == before and not sim.created
    assert sim.host.store.host_place_get(REQ) is None
    assert (sim.copy / "a.txt").read_text() == ("edited" if how == "dirty" else "one")


def test_ahead_copy_is_used_as_it_is(sim: Sim) -> None:
    sim.fetch_carried()
    git(sim.copy, "merge", "-q", "--ff-only", sim.h2)
    own = commit(sim.copy, "own.txt")
    reply = sim.post()
    assert reply.status_code == 200 and git(sim.copy, "rev-parse", "HEAD") == own
    assert "ahead" in reply.json()["copy_note"]


def test_behind_copy_with_a_live_session_is_in_use_and_nothing_moves(sim: Sim) -> None:
    sim.live = [os.path.realpath(sim.copy / "sub")]
    reply = sim.post()
    assert (reply.status_code, code_of(reply)) == (409, "copy_in_use")
    assert git(sim.copy, "rev-parse", "HEAD") == sim.h1 and not sim.created


def test_copy_at_the_head_with_a_live_session_is_used(sim: Sim) -> None:
    git(sim.copy, "merge", "-q", "--ff-only", sim.h2)
    sim.live = [os.path.realpath(sim.copy)]
    assert sim.post().status_code == 200 and len(sim.created) == 1


def test_a_live_session_elsewhere_does_not_block(sim: Sim) -> None:
    sim.live = [os.path.realpath(sim.copy) + "-other"]
    assert sim.post().status_code == 200


def test_takes_work_off_is_403_and_read_now(sim: Sim) -> None:
    sim.restrictions = Restrictions(may_host_agents=False)
    reply = sim.post()
    assert reply.status_code == 403 and not sim.created and git(sim.copy, "rev-parse", "HEAD") == sim.h1
    sim.restrictions = Restrictions()
    assert sim.post().status_code == 200


def test_same_request_id_twice_is_one_session(sim: Sim) -> None:
    first = sim.post()
    HOLDS._entries.clear()
    second = sim.post(profile_name="other")
    assert first.status_code == second.status_code == 200 and first.json() == second.json() and len(sim.created) == 1


def test_request_id_of_another_caller_is_refused(sim: Sim) -> None:
    assert sim.post().status_code == 200
    sim.principal = peer_auth.Principal("peer", SimpleNamespace(peer_install_id="iid-x"))
    assert sim.post().status_code == 403
    with closing(connect(db_path_for(sim.state), create=False)) as conn:
        replicas.accept_replica(conn, home_install_id="iid-x", project_uid="p2x23456", name="other", root=str(sim.tmp / "copy2"))
    reply = sim.post(project_uid="p2x23456")
    assert (reply.status_code, code_of(reply)) == (409, "request_id_taken") and len(sim.created) == 1


def test_profile_by_name_else_family_default_with_posture_flags(sim: Sim) -> None:
    sim.profiles = [profile("fast", "ask")]
    sim.post(profile_name="fast")
    assert sim.created[0]["plan"].agent_type == "fast" and sim.created[0]["plan"].extra_args == []
    sim.created.clear()
    with closing(sim.host.store._connect()) as conn:
        conn.execute("DELETE FROM host_session_places")
    sim.profiles = [profile("cld", "harness_default", default=True)]
    reply = sim.post(profile_name="nope", posture="accept_edits")
    plan = sim.created[0]["plan"]
    assert plan.agent_type == "claude" and plan.extra_args == ["--permission-mode", "acceptEdits"]
    assert "no profile named nope" in reply.json()["profile_used"]


def test_unknown_posture_never_resolves_to_skip_all(sim: Sim) -> None:
    sim.profiles = [profile("cld", "skip_all", default=True), profile("safe", "ask")]
    sim.post(posture="unknown")
    run = resolved(sim)
    assert "--dangerously-skip-permissions" not in run.command and run.display.permissions == "ask"


def test_only_a_skip_all_default_refuses_posture_unsafe(sim: Sim) -> None:
    for profiles in ([profile("cld", "skip_all", default=True)], []):
        sim.profiles = profiles
        reply = sim.post(posture="unknown")
        assert (reply.status_code, code_of(reply)) == (409, "posture_unsafe") and not sim.created and HOLDS.owner(REQ) is None
        with closing(sim.host.store._connect()) as conn:
            conn.execute("DELETE FROM host_session_places")


def test_a_harness_default_profile_with_a_custom_command_is_not_trusted(sim: Sim) -> None:
    risky = profile("fast", "harness_default", custom_command={"script": 'claude --dangerously-skip-permissions "$@"'})
    sim.profiles = [risky, profile("safe", "ask", default=True)]
    reply = sim.post(profile_name="fast", posture="ask")
    run = resolved(sim)
    assert reply.status_code == 200 and sim.created[0]["plan"].agent_type == "claude" and "--dangerously-skip-permissions" not in run.command


def test_a_named_profile_above_the_starters_posture_is_not_used(sim: Sim) -> None:
    sim.profiles = [profile("fast", "skip_all"), profile("safe", "ask", default=True)]
    reply = sim.post(profile_name="fast", posture="ask")
    plan = sim.created[0]["plan"]
    assert plan.agent_type == "claude" and plan.extra_args == [] and "not usable" in reply.json()["profile_used"]


def test_codex_without_the_posture_falls_to_ask(sim: Sim) -> None:
    sim.profiles = [profile("cdx", "harness_default", "codex", default=True)]
    sim.post(family="codex", posture="accept_edits")
    assert sim.created[0]["plan"].extra_args == ["--ask-for-approval", "on-request"]


def test_relay_login_is_marked_and_pinned(sim: Sim) -> None:
    sim.accounts = AccountPick(None, {"CLAUDE_CONFIG_DIR": "/relay/dir"}, "relayacct", "relay")
    reply = sim.post(account_key="relayacct")
    assert reply.json()["account_how"] == "relay" and sim.created[0]["plan"].extra_env == {"CLAUDE_CONFIG_DIR": "/relay/dir"}
    assert session_pin.pin_for(sim.config, sim.uuid) == "relayacct"


def test_no_login_refuses_account_not_usable(sim: Sim) -> None:
    sim.accounts = JobError("account_not_usable", "no claude login here", 409)
    reply = sim.post()
    assert (reply.status_code, code_of(reply)) == (409, "account_not_usable") and not sim.created and git(sim.copy, "rev-parse", "HEAD") == sim.h1


def test_pin_is_never_written_over_an_owner_pin(sim: Sim) -> None:
    assert session_pin.carry(sim.config, sim.uuid, "owners-pick")
    sim.accounts = AccountPick("other", {}, "other", "same")
    assert sim.post().status_code == 200
    assert session_pin.pin_for(sim.config, sim.uuid) == "owners-pick"


def test_pegged_computer_refuses_and_leaves_no_hold(sim: Sim, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: {"pressure": {"pegged": True, "why": "9.6 of 10 cores busy"}})
    reply = sim.post()
    assert (reply.status_code, code_of(reply)) == (503, "pegged") and not sim.created and HOLDS.owner(REQ) is None


def test_admission_refusal_is_host_busy(sim: Sim) -> None:
    sim.host._admit = lambda work: "this computer has no memory to spare"
    reply = sim.post()
    assert (reply.status_code, code_of(reply)) == (503, "host_busy") and not sim.created


def test_failed_create_drops_the_hold_and_stops_the_half_made_session(sim: Sim) -> None:
    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("no tmux")

    sim.host.agent.deps.create_worker = boom
    stops: List[str] = []

    async def stop(session_id: str, session_uuid: Any = None) -> None:
        stops.append(session_id)

    sim.host.agent.deps.stop_worker = stop
    reply = sim.post()
    assert reply.status_code == 503 and HOLDS.owner(REQ) is None and len(stops) == 1


def test_project_must_be_a_copy_here_and_the_caller_its_home(sim: Sim) -> None:
    reply = sim.post(project_uid="nope1234")
    assert (reply.status_code, code_of(reply)) == (409, "project_not_here")


def test_body_cannot_name_a_path_or_a_command(sim: Sim) -> None:
    for extra in ({"working_dir": "/etc"}, {"extra_args": ["--x"]}, {"env": {"A": "b"}}):
        assert sim.post(**extra).status_code == 422
    assert not sim.created


def test_owner_login_is_refused(sim: Sim) -> None:
    sim.principal = peer_auth.OWNER
    reply = sim.post()
    assert reply.status_code == 403 and code_of(reply) == "peer_token_required"


def test_strings_from_the_body_are_cleaned(sim: Sim) -> None:
    sim.post(label="hi\x1b[31m there\n")
    assert "\x1b" not in sim.created[0]["label"] and "\n" not in sim.created[0]["label"]


def test_branch_differs_and_copy_is_clean_behind_moves_to_that_branch(sim: Sim) -> None:
    git(sim.home_repo, "checkout", "-q", "-b", "feat")
    head = commit(sim.home_repo, "c.txt")
    git(sim.copy, "fetch", "-q", str(sim.home_repo), "feat:refs/carnivore/iid-a/heads/feat")
    state = copy_ready.ready(str(sim.copy), HOME, "feat", head, air_gap=False)
    assert state.ok and state.moved and git(sim.copy, "rev-parse", "HEAD") == head and git(sim.copy, "rev-parse", "main") == sim.h1


def test_copy_ready_refuses_a_head_that_never_arrived(sim: Sim) -> None:
    assert copy_ready.ready(str(sim.copy), HOME, "main", "f" * 40, air_gap=False).code == "copy_not_ready"
    assert copy_ready.ready(str(sim.tmp), HOME, "main", sim.h2, air_gap=False).code == "copy_not_ready"
    assert copy_ready.ready(str(sim.copy), HOME, "main", "zz", air_gap=False).code == "copy_not_ready"
    assert git(sim.copy, "rev-parse", "HEAD") == sim.h1


def test_max_agents_bounds_placed_sessions(sim: Sim) -> None:
    sim.restrictions = Restrictions(max_agents=1)

    async def listed(session_id: str) -> bool:
        return True

    sim.host.agent.deps.listed = listed
    assert sim.post().status_code == 200
    second = sim.post(request_id="b" * 32)
    assert (second.status_code, second.json()["detail"]["rule"]) == (403, "max_agents") and len(sim.created) == 1
    assert sim.post().status_code == 200 and len(sim.created) == 1


def test_a_waiter_keeps_the_keyed_lock_alive() -> None:
    import asyncio

    locks = session_host._KeyedLocks()
    order: List[str] = []

    async def worker(name: str, gate: asyncio.Event) -> None:
        async with locks.hold("k"):
            order.append(name)
            await gate.wait()

    async def run() -> None:
        g1, g2, g3 = asyncio.Event(), asyncio.Event(), asyncio.Event()
        t1, t2 = asyncio.create_task(worker("1", g1)), asyncio.create_task(worker("2", g2))
        await asyncio.sleep(0.01)
        g1.set()
        await t1
        t3 = asyncio.create_task(worker("3", g3))
        await asyncio.sleep(0.01)
        assert order == ["1", "2"]
        g2.set()
        g3.set()
        await asyncio.gather(t2, t3)
        assert order == ["1", "2", "3"] and not locks._held

    asyncio.run(run())


def test_a_live_folder_spelled_in_another_case_is_inside(tmp_path: Path) -> None:
    root = tmp_path / "Copy"
    (root / "sub").mkdir(parents=True)
    other = str(tmp_path / "copy" / "sub")
    if not os.path.exists(other):
        pytest.skip("this disk is case sensitive")
    assert session_host._inside(other, str(root)) and not session_host._inside(str(tmp_path), str(root))


def test_the_default_live_folder_read_skips_dead_and_asleep_and_resolves_links(tmp_path: Path) -> None:
    import asyncio

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    def info(folder: Any, tmux: Any, status: Any) -> Any:
        return SimpleNamespace(tmux_session=tmux, activity_status=status, session=SimpleNamespace(working_dir=str(folder)))

    infos = [info(link, "t1", "idle"), info(tmp_path / "dead", "t2", "dead"), info(tmp_path / "asleep", None, "idle")]

    async def listing() -> Any:
        return infos

    app = SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(list_session_infos=listing)))
    assert asyncio.run(session_host.default_live_folders(app)) == [os.path.realpath(str(real))]


def test_wire_refuses_an_option_like_branch_and_an_odd_effort() -> None:
    base = dict(request_id=REQ, project_uid="p", home_head="b" * 40)
    for bad in ("-f", "a..b", "a b", "x.lock", "a/"):
        with pytest.raises(ValueError):
            PeerCreateBody(**base, branch=bad)
    with pytest.raises(ValueError):
        PeerCreateBody(**base, branch="main", effort='x" y')
    assert PeerCreateBody(**base, branch="feat/a-1", effort="high").effort == "high"
