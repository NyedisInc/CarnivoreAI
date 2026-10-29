
from __future__ import annotations

import asyncio
import dataclasses
import functools
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_move_routes as move_routes  # noqa: E402
from src.api import federation_pack_transport_routes as transport_routes  # noqa: E402
from src.api import pack_migrate_env as env_mod  # noqa: E402
from src.api import pack_move_env, peer_auth, recreate_action  # noqa: E402
from src.api import recreate_routes as rr  # noqa: E402
from src.config import settings  # noqa: E402
from src.core import session_change_notice, session_store  # noqa: E402
from src.core.account_switch import restart_account  # noqa: E402
from src.core.claude_transcript_correlate import slugify_project_dir  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants  # noqa: E402
from src.core.launch_profiles.resolve import LaunchProfileNotFound  # noqa: E402
from src.core.pack.machines import config_state, restrictions  # noqa: E402
from src.core.pack.migrate import apply, transcripts  # noqa: E402
from src.core.pack.migrate.plan import MigrateError  # noqa: E402
from src.core.pack.move import account, ops, session_move, turn  # noqa: E402
from src.core.pack.move.receive import MoveTarget  # noqa: E402
from src.core.pack.relay import target_side  # noqa: E402
from src.core.project_writes import create_project  # noqa: E402
from src.core.session_recreate_presence import TMUX_GONE, TmuxPresence  # noqa: E402

CONVERSATION = "0198c8f0-1111-7222-8333-944445555666"
OTHER_CONVERSATION = "0198c8f0-2222-7222-8333-944445555666"


class Machine:

    def __init__(self, tmp: Path, name: str, install_id: str) -> None:
        self.name, self.install_id = name, install_id
        self.state, self.projects, self.claude = tmp / f"{name}-state", tmp / f"{name}-projects", tmp / f"{name}-claude"
        for folder in (self.state, self.projects, self.claude):
            folder.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        self.restrictions = restrictions.Restrictions()
        self.launched: List[Dict[str, Any]] = []
        self.app = FastAPI()
        self.app.include_router(move_routes.router, prefix="/api/v1")
        self.app.include_router(transport_routes.router, prefix="/api/v1")
        self.app.state.session_manager = SimpleNamespace(create_session=self._create_session,
                                                                get_session_info=self._get_session_info)
        self.client = TestClient(self.app)

    async def _create_session(self, **kw: Any) -> Any:
        self.launched.append(kw)
        EVENTS.append(f"{self.name}:launch")
        return SimpleNamespace(id="ses_new", tmux_session=kw.get("project_name"))

    async def _get_session_info(self, session_id: str) -> None:
        return None

    def conn(self):
        return connect(db_path_for(self.state), create=False)


EVENTS: List[str] = []


@pytest.fixture()
def world(monkeypatch, tmp_path):
    EVENTS.clear()
    a, b = Machine(tmp_path, "a", "iid-a"), Machine(tmp_path, "b", "iid-b")
    machines = {"iid-a": a, "iid-b": b}
    current = [a]
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: current[0].state, raising=True)
    monkeypatch.setattr(env_mod, "_install_id", lambda: current[0].install_id)
    monkeypatch.setattr(env_mod, "_labels", lambda: {"iid-a": "mac", "iid-b": "studio"})
    monkeypatch.setattr(transcripts, "transcript_roots", lambda: (current[0].claude,))
    monkeypatch.setattr(config_state, "default", lambda: type("S", (), {"restrictions": lambda self: current[0].restrictions})())
    relay = tmp_path / "relay"
    (relay / "larkspur").mkdir(parents=True)
    monkeypatch.setattr(target_side, "relay_profile_dir", lambda key, sender, home=None: str(relay / key))
    monkeypatch.setattr(pack_move_env, "move_target", lambda: MoveTarget(
        env=dataclasses.replace(env_mod.target_env(), projects_dir=str(current[0].projects), transcripts_root=current[0].claude),
        launch_for=lambda key, sender: account.launch_for(key, sender, tmp_path / "no-config.json")))
    monkeypatch.setattr("src.core.session_imported_restart.default_projects_dir", lambda: current[0].claude)
    monkeypatch.setattr(rr, "_measure_presence", lambda name, socket: TmuxPresence(TMUX_GONE))
    monkeypatch.setattr(recreate_action.rr, "validate_agent_choice", lambda s, agent, model=None, extra_args=None: SimpleNamespace(
        verdict="accepted", command="claude " + " ".join(extra_args or []), detail=""))

    async def resolve(*args: Any, **kw: Any):
        return restart_account.AccountPlan(account_id=kw.get("requested"))

    async def persist(*args: Any, **kw: Any) -> None:
        return None

    monkeypatch.setattr(restart_account, "family_of", lambda agent_type: "claude")
    monkeypatch.setattr(restart_account, "resolve", resolve)
    monkeypatch.setattr(restart_account, "persist", persist)
    monkeypatch.setattr("src.core.session_agent_choice.configured_wrapper_ids", lambda s: ["claude"])
    monkeypatch.setattr(session_change_notice, "publish", lambda *args, **kw: None)

    def link(sender: Machine, receiver: Machine):
        with closing(receiver.conn()) as conn:
            if not any(g.peer_install_id == sender.install_id for g in grants.list_grants(conn)):
                key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([7]) * 32))
                grants.create_grant(conn, peer_install_id=sender.install_id, public_key=key, label=sender.install_id, scopes=("migrate",))
            grant = next(g for g in grants.list_grants(conn) if g.peer_install_id == sender.install_id)
        principal = peer_auth.Principal("peer", grant)
        receiver.app.dependency_overrides[move_routes._require_migrate] = lambda: principal
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

    return a, b, link


def seed(a: Machine, b: Machine, account_of: Dict[str, str]):
    root_a, root_b = a.projects / "trader", b.projects / "trader"
    root_a.mkdir()
    root_b.mkdir()
    with closing(a.conn()) as conn:
        project = create_project(conn, name="trader", path=str(root_a))
        uid = conn.execute("SELECT uid FROM projects WHERE id = ?", (project["id"],)).fetchone()[0]
        for uuid, conv, name in (("sess-0001-aaaa", CONVERSATION, "carnivore_trader"), ("sess-0002-bbbb", OTHER_CONVERSATION, "carnivore_other")):
            conn.execute(
                "INSERT INTO sessions (session_uuid, project_id, working_dir, tmux_name, tmux_created_epoch, origin, agent_type, agent_family, "
                "agent_family_source, claude_session_uuid, claude_session_uuid_source, title, lifecycle, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, 'created', 'claude', 'claude', 'launch', ?, 'registry', ?, 'running', 't', 't')",
                (uuid, project["id"], str(root_a), name, conv, name))
            folder = a.claude / slugify_project_dir(str(root_a))
            folder.mkdir(exist_ok=True)
            (folder / f"{conv}.jsonl").write_text('{"type":"user","n":"' + conv[:4] + '"}\n')
        conn.commit()
    with closing(b.conn()) as conn:
        made = create_project(conn, name="trader", path=str(root_b))
        conn.execute("UPDATE projects SET uid = ?, pack_state = 'replica', home_install_id = 'iid-a' WHERE id = ?", (uid, made["id"]))
        conn.commit()
    return uid, root_a, root_b


def subject_of(a: Machine, uuid: str) -> Dict[str, Any]:
    with closing(a.conn()) as conn:
        return session_move.read_subject(conn, uuid)


def hooks_for(a: Machine, statuses: List[str], accounts: Dict[str, str]) -> session_move.Hooks:
    script = list(statuses)

    async def find(uuid: str) -> Any:
        status = script.pop(0) if len(script) > 1 else script[0]
        EVENTS.append(f"a:find:{status}")
        return SimpleNamespace(activity_status=status, activity_hint=None, startup_gate="ready")

    async def sleep(uuid: str) -> None:
        EVENTS.append("a:sleep")
        with closing(a.conn()) as conn:
            conn.execute("UPDATE sessions SET lifecycle = 'stopped', lifecycle_source = 'slept_by_user' WHERE session_uuid = ?", (uuid,))
            conn.commit()

    async def wake(uuid: str) -> None:
        EVENTS.append("a:rewake")

    async def hide(uuid: str) -> None:
        EVENTS.append("a:hide")
        with closing(a.conn()) as conn:
            session_store.archive_session(conn, uuid)

    return session_move.Hooks(find=find, sleep=sleep, wake=wake, hide=hide, account_key=lambda uuid: accounts[uuid])


def test_a_busy_session_is_held_then_moves_and_resumes_once_and_a_session_with_no_login_is_refused_first(world, monkeypatch) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    accounts = {"sess-0001-aaaa": "larkspur", "sess-0002-bbbb": "no-such-login"}
    env = env_mod.source_env()

    with pytest.raises(MigrateError) as refused:
        asyncio.run(session_move.move_session(env, hooks_for(a, ["idle"], accounts), apply.guarded(link(a, b)), subject=subject_of(a, "sess-0002-bbbb"),
                                              target_install_id="iid-b", target_label="studio", wait_seconds=5))
    assert refused.value.code == "account_not_usable" and refused.value.step == "check"
    assert "a:sleep" not in EVENTS and b.launched == []
    with closing(b.conn()) as conn:
        assert conn.execute("SELECT 1 FROM sessions WHERE session_uuid = 'sess-0002-bbbb'").fetchone() is None
    assert not list((b.state / "pack" / "inbox").glob("*")) if (b.state / "pack" / "inbox").exists() else True

    EVENTS.clear()
    done = asyncio.run(session_move.move_session(env, hooks_for(a, ["working", "working", "question", "idle"], accounts), apply.guarded(link(a, b)),
                                                 subject=subject_of(a, "sess-0001-aaaa"), target_install_id="iid-b", target_label="studio", wait_seconds=5))
    assert done["machine"] == "studio"
    assert EVENTS.index("a:sleep") > EVENTS.index("a:find:idle") and "a:find:working" in EVENTS[:EVENTS.index("a:sleep")]
    assert EVENTS.index("a:sleep") < EVENTS.index("b:launch") < EVENTS.index("a:hide"), EVENTS

    assert len(b.launched) == 1
    launch = b.launched[0]
    relay_dir = Path(target_side.relay_profile_dir("larkspur", "iid-a"))
    argv = launch["agent_extra_args"]
    assert argv.count("--resume") == 1 and argv[argv.index("--resume") + 1] == CONVERSATION, argv
    assert launch["extra_env"] == {"CLAUDE_CONFIG_DIR": str(Path(target_side.relay_profile_dir("larkspur", "iid-a")))}
    assert launch["working_dir"] == str(root_b)
    filed = b.claude / slugify_project_dir(str(root_b)) / f"{CONVERSATION}.jsonl"
    assert (relay_dir / "projects" / slugify_project_dir(str(root_b)) / f"{CONVERSATION}.jsonl").read_text() == filed.read_text(), "a relayed login reads its own profile's projects folder"
    assert filed.read_text() == (a.claude / slugify_project_dir(str(root_a)) / f"{CONVERSATION}.jsonl").read_text()
    assert not (b.claude / slugify_project_dir(str(root_b)) / f"{OTHER_CONVERSATION}.jsonl").exists(), "only this conversation is carried"

    with closing(b.conn()) as conn:
        landed = dict(conn.execute("SELECT * FROM sessions WHERE session_uuid = 'sess-0001-aaaa'").fetchone())
        assert landed["claude_session_uuid"] == CONVERSATION and landed["working_dir"] == str(root_b) and landed["archived_at"] is None
        assert ops.view(conn, done["op_id"])["state"] == "moved"
    with closing(a.conn()) as conn:
        old = dict(conn.execute("SELECT * FROM sessions WHERE session_uuid = 'sess-0001-aaaa'").fetchone())
        forward = ops.forward_for(conn, "sess-0001-aaaa")
    assert old["archived_at"] is not None, "the old row is off every list"
    assert forward["target_install_id"] == "iid-b" and forward["detail"]["machine"] == "studio" and forward["claude_session_uuid"] == CONVERSATION


def test_a_move_stops_a_resting_agents_open_shells_itself_and_a_copy_never_does(world, monkeypatch) -> None:
    import os
    import signal
    import subprocess

    a, b, link = world
    seed(a, b, {})
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    accounts = {"sess-0001-aaaa": "larkspur", "sess-0002-bbbb": "larkspur"}
    env = env_mod.source_env()
    tree = subprocess.Popen(["sh", "-c", "sleep 60 & wait"], start_new_session=True)
    shells_open = {"on": True}

    def hooks_with_shells() -> session_move.Hooks:
        hooks = hooks_for(a, ["idle"], accounts)

        async def find(uuid: str) -> Any:
            if not shells_open["on"]:
                return SimpleNamespace(activity_status="idle", activity_hint=None, startup_gate="ready", background_open=None)
            return SimpleNamespace(activity_status="working_subagent", activity_hint=None, startup_gate="ready", background_open=1, subagents_running=0)

        async def background_members(uuid: str) -> List[Any]:
            EVENTS.append("a:measure_shells")
            return [(tree.pid, "unused")]

        async def sleep(uuid: str) -> None:
            assert tree.poll() is None, "no shell may be signalled while the agent is alive: claude starts a new turn when a shell exits under it"
            await hooks.sleep(uuid)

        async def stop_members(uuid: str, members: List[Any]) -> List[int]:
            EVENTS.append("a:stop_shells")
            assert "a:sleep" in EVENTS, "the shells are stopped only after the agent is asleep"
            os.killpg(tree.pid, signal.SIGKILL)
            tree.wait()
            shells_open["on"] = False
            return [tree.pid]

        return dataclasses.replace(hooks, find=find, sleep=sleep, background_members=background_members, stop_members=stop_members)

    try:
        EVENTS.clear()
        copied = asyncio.run(session_move.move_session(env, hooks_with_shells(), apply.guarded(link(a, b)), subject=subject_of(a, "sess-0002-bbbb"),
                                                       target_install_id="iid-b", target_label="studio", wait_seconds=5, mode="copy"))
        assert copied["target_session_uuid"] != "sess-0002-bbbb" and "a:stop_shells" not in EVENTS and tree.poll() is None, "a copy never stops the original's shells"
        EVENTS.clear()
        asyncio.run(session_move.move_session(env, hooks_with_shells(), apply.guarded(link(a, b)), subject=subject_of(a, "sess-0001-aaaa"),
                                              target_install_id="iid-b", target_label="studio", wait_seconds=5))
        assert EVENTS.index("a:measure_shells") < EVENTS.index("a:sleep") < EVENTS.index("a:stop_shells") < EVENTS.index("b:launch"), EVENTS
        assert tree.poll() is not None, "the throwaway shell tree is gone"
    finally:
        if tree.poll() is None:
            os.killpg(tree.pid, signal.SIGKILL)
            tree.wait()


def test_a_move_is_refused_at_the_check_when_the_launch_profile_is_not_on_the_target(world, monkeypatch) -> None:
    a, b, link = world
    seed(a, b, {})
    with closing(a.conn()) as conn:
        conn.execute("UPDATE sessions SET agent_type = 'claude-chrome' WHERE session_uuid = 'sess-0001-aaaa'")
        conn.commit()
    here = {"profiles": set()}

    def profile_check(agent_type):
        if agent_type not in here["profiles"] and agent_type != "claude":
            raise LaunchProfileNotFound(agent_type)

    base = pack_move_env.move_target
    monkeypatch.setattr(pack_move_env, "move_target", lambda: dataclasses.replace(base(), profile_check=profile_check))
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    accounts, env = {"sess-0001-aaaa": "larkspur"}, env_mod.source_env()

    def move():
        return asyncio.run(session_move.move_session(env, hooks_for(a, ["idle"], accounts), apply.guarded(link(a, b)), subject=subject_of(a, "sess-0001-aaaa"),
                                                     target_install_id="iid-b", target_label="studio", wait_seconds=5))

    with pytest.raises(MigrateError) as refused:
        move()
    assert refused.value.code == "launch_profile_not_on_target" and refused.value.step == "check" and "claude-chrome" in refused.value.detail
    assert "a:sleep" not in EVENTS and b.launched == []
    with closing(b.conn()) as conn:
        assert conn.execute("SELECT 1 FROM sessions WHERE session_uuid = 'sess-0001-aaaa'").fetchone() is None
    here["profiles"].add("claude-chrome")
    monkeypatch.setattr("src.core.session_agent_choice.configured_wrapper_ids", lambda s: ["claude", "claude-chrome"])
    assert move()["machine"] == "studio"


def test_a_cancel_before_the_point_of_no_return_leaves_the_session_here_and_after_it_is_refused(world, monkeypatch) -> None:
    from fastapi import HTTPException
    from src.api import pack_ops_routes
    from src.core.pack.move import inflight, op_status

    a, b, link = world
    seed(a, b, {})
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    accounts, env = {"sess-0001-aaaa": "larkspur"}, env_mod.source_env()

    def row_state(op_id: str) -> Dict[str, Any]:
        with closing(a.conn()) as conn:
            return dict(conn.execute("SELECT state, step, error_code FROM pack_session_moves WHERE id = ?", (op_id,)).fetchone())

    async def until(check) -> None:
        for _ in range(400):
            if check():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("never reached")

    async def run(statuses: List[str], gate_when) -> tuple:
        real, reached, gate = link(a, b), asyncio.Event(), asyncio.Event()

        async def request(method: str, path: str, **kw: Any):
            if gate_when(path, kw):
                reached.set()
                await gate.wait()
            return await real(method, path, **kw)

        op_id = "op" + "0" * 30
        task = asyncio.get_running_loop().create_task(session_move.move_session(
            env, hooks_for(a, statuses, accounts), apply.guarded(request), subject=subject_of(a, "sess-0001-aaaa"), target_install_id="iid-b",
            target_label="studio", op_id=op_id, wait_seconds=30))
        inflight.register(op_id, task, ("sess-0001-aaaa",))
        return op_id, task, reached, gate

    async def scenario() -> None:
        op_id, task, _, _ = await run(["working"], lambda path, kw: False)
        await until(lambda: EVENTS.count("a:find:working") >= 2)
        assert (await pack_ops_routes.cancel_op(op_id)) == {"op_id": op_id, "state": "cancelling"}
        with pytest.raises(asyncio.CancelledError):
            await task
        assert row_state(op_id) == {"state": "failed", "step": "wait", "error_code": "cancelled"}
        assert "a:sleep" not in EVENTS and b.launched == [] and inflight.op_for("sess-0001-aaaa") is None
        with closing(a.conn()) as conn:
            assert conn.execute("SELECT archived_at FROM sessions WHERE session_uuid = 'sess-0001-aaaa'").fetchone()[0] is None
            assert [o["id"] for o in op_status.recent(conn) if o["running"]] == []

        EVENTS.clear()
        op_id, task, reached, _ = await run(["idle"], lambda path, kw: kw.get("content") is not None)
        await asyncio.wait_for(reached.wait(), 10)
        assert "a:sleep" in EVENTS and (await pack_ops_routes.cancel_op(op_id))["state"] == "cancelling"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert EVENTS[-1] == "a:rewake" and "a:hide" not in EVENTS and b.launched == []
        assert row_state(op_id)["error_code"] == "cancelled"

        EVENTS.clear()
        op_id, task, reached, gate = await run(["idle"], lambda path, kw: path == session_move.RECEIVE and kw.get("json", {}).get("dry_run") is False)
        await asyncio.wait_for(reached.wait(), 10)
        with pytest.raises(HTTPException) as refused:
            await pack_ops_routes.cancel_op(op_id)
        assert refused.value.status_code == 409 and refused.value.detail["code"] == "past_point_of_no_return" and "starting the agent" in refused.value.detail["detail"]
        gate.set()
        assert (await task)["machine"] == "studio"
        assert row_state(op_id)["state"] == "moved" and len(b.launched) == 1

        with closing(a.conn()) as conn:
            ops.create(conn, op_id="ghost", role="source", session_uuid="sess-0002-bbbb", claude_session_uuid=None, source_install_id="iid-a", target_install_id="iid-b")
            assert op_status.one(conn, "ghost")["interrupted"] is True and op_status.close_orphans(conn) == 1
            assert op_status.one(conn, "ghost")["running"] is False and op_status.one(conn, "ghost")["error_code"] == "interrupted"

    asyncio.run(scenario())


def test_stop_running_agents_box_off_refuses_naming_the_agent_and_on_interrupts_moves_wakes_and_continues_only_that_one(world, monkeypatch) -> None:
    from fastapi import HTTPException
    from src.api import pack_move_routes, pack_send_routes

    a, b, link = world
    seed(a, b, {})
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    accounts = {"sess-0001-aaaa": "larkspur", "sess-0002-bbbb": "larkspur"}
    env = env_mod.source_env()
    status = {"sess-0001-aaaa": "working", "sess-0002-bbbb": "idle"}
    pressed: List[str] = []
    pasted: List[Dict[str, Any]] = []

    def hooks() -> session_move.Hooks:
        base = hooks_for(a, ["idle"], accounts)

        async def find(uuid: str) -> Any:
            return SimpleNamespace(activity_status=status[uuid], activity_hint=None, startup_gate="ready", background_open=None)

        async def interrupt(uuid: str) -> None:
            EVENTS.append("a:interrupt")
            pressed.append(uuid)
            status[uuid] = "idle"

        return dataclasses.replace(base, find=find, interrupt=interrupt)

    def peer_link(sender: Machine, receiver: Machine):
        real = link(sender, receiver)

        async def request(method: str, path: str, **kw: Any):
            if method == "GET" and path == "/sessions/list":
                return 200, [{"session_uuid": "sess-0001-aaaa", "session": {"id": "ses_new"}}, {"session_uuid": "sess-0002-bbbb", "session": {"id": "ses_two"}}]
            if path.endswith("/skills/one-shot"):
                pasted.append({"path": path, **kw["json"]})
                EVENTS.append("b:continue")
                return 200, {"submitted": True}
            return await real(method, path, **kw)

        return request

    monkeypatch.setattr(pack_move_routes, "find_peer", lambda name: SimpleNamespace(peer_install_id="iid-b", label="studio"))
    monkeypatch.setattr(pack_send_routes, "find_peer", lambda name: SimpleNamespace(peer_install_id="iid-b", label="studio"))
    monkeypatch.setattr(env_mod, "link_request", lambda install_id, timeout=0: peer_link(a, b))
    monkeypatch.setattr(pack_move_env, "source_hooks", lambda state: hooks())
    monkeypatch.setattr(pack_move_routes.projects_service, "guard_writable", lambda s: None)
    fake_request = SimpleNamespace(app=SimpleNamespace(state=None))

    with pytest.raises(HTTPException) as refused:
        asyncio.run(pack_move_routes.start_send("sess-0001-aaaa", "studio", 5, fake_request))
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "agents_running"
    assert "carnivore_trader is running" in refused.value.detail["detail"] and "stop running agents now" in refused.value.detail["detail"]
    checked = asyncio.run(pack_send_routes.send_check_route("sess-0001-aaaa", pack_send_routes.CheckBody(machine="studio"), fake_request))
    assert checked["running"] is True and checked["move"]["ok"] is False and checked["move"]["reason"] == "agents_running" and "carnivore_trader" in checked["move"]["detail"]
    assert "a:sleep" not in EVENTS and b.launched == [] and pressed == []
    from src.core.pack.move import interrupt as interrupt_mod
    shells_only_row = dict(activity_hint=None, startup_gate="ready", background_open=1)
    assert not interrupt_mod.is_running(SimpleNamespace(activity_status="working_subagent", subagents_running=0, **shells_only_row)), "one shell alone is not a running turn"
    assert interrupt_mod.is_running(SimpleNamespace(activity_status="working_subagent", subagents_running=1, **shells_only_row))
    with closing(a.conn()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pack_session_moves").fetchone()[0] == 0
    assert asyncio.run(pack_send_routes.send_check_route("sess-0002-bbbb", pack_send_routes.CheckBody(machine="studio"), fake_request))["running"] is False

    EVENTS.clear()
    running_one = asyncio.run(session_move.move_session(env, hooks(), apply.guarded(peer_link(a, b)), subject=subject_of(a, "sess-0001-aaaa"),
                                                        target_install_id="iid-b", target_label="studio", wait_seconds=5, stop_running=True))
    assert EVENTS.index("a:interrupt") < EVENTS.index("a:sleep") < EVENTS.index("b:launch") < EVENTS.index("a:hide") < EVENTS.index("b:continue"), EVENTS
    assert pressed == ["sess-0001-aaaa"] and [(p["path"], p["idle_only"]) for p in pasted] == [("/sessions/ses_new/skills/one-shot", True)]
    assert pasted[0]["text"].startswith("continue. you moved to studio. your project folder there is ")
    with closing(a.conn()) as conn:
        view = ops.view(conn, running_one["op_id"])
    assert view["state"] == "moved" and view["detail"]["told"] == 1 and view["detail"]["continue_failed"] == []

    EVENTS.clear()
    pasted.clear()
    asyncio.run(session_move.move_session(env, hooks(), apply.guarded(peer_link(a, b)), subject=subject_of(a, "sess-0002-bbbb"),
                                          target_install_id="iid-b", target_label="studio", wait_seconds=5, stop_running=True))
    assert "b:launch" in EVENTS and pressed == ["sess-0001-aaaa"] and pasted == [], "an agent that was not interrupted is woken but told nothing"

    status["sess-0001-aaaa"] = "working"
    monkeypatch.setattr(pack_move_routes.interrupt, "CONTINUE_WAIT_SECONDS", 0.0, raising=False)

    async def refuse_paste(method: str, path: str, **kw: Any):
        if path.endswith("/skills/one-shot"):
            return 409, {"detail": {"message": "the agent is not at a ready prompt"}}
        return await peer_link(a, b)(method, path, **kw)

    with closing(a.conn()) as conn:
        conn.execute("UPDATE sessions SET archived_at = NULL, lifecycle = 'running', session_uuid = 'sess-0003-cccc', tmux_name = 'carnivore_third' WHERE session_uuid = 'sess-0001-aaaa'")
        conn.commit()
    status["sess-0003-cccc"] = "working"
    accounts["sess-0003-cccc"] = "larkspur"
    with closing(b.conn()) as conn:
        conn.execute("DELETE FROM sessions WHERE session_uuid = 'sess-0001-aaaa'")
        conn.commit()
    done = asyncio.run(session_move.move_session(env, hooks(), apply.guarded(refuse_paste), subject=subject_of(a, "sess-0003-cccc"), target_install_id="iid-b",
                                                 target_label="studio", wait_seconds=5, stop_running=True))
    with closing(a.conn()) as conn:
        view = ops.view(conn, done["op_id"])
    assert view["state"] == "moved" and view["detail"]["told"] == 0 and view["detail"]["continue_failed"][0]["name"] == "carnivore_trader"
