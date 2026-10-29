
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from typing import Any, List

import pytest
import structlog

from src.core import db as core_db
from src.models.utc_time import utc_now
from src.core.hosts import registry as host_registry
from src.core.hosts import remote_readopt, remote_resume
from src.core.inventory import db_trace, file_trace
from src.core.inventory.model import SessionIdentity



def _fake_host() -> Any:
    calls: List[str] = []

    async def noop(name: str) -> None:
        calls.append(name)

    host = SimpleNamespace(
        host_key="studio", calls=calls, is_up=True,
        close=lambda: noop("close"),
        channel=SimpleNamespace(stop=lambda: noop("channel")),
        pool=SimpleNamespace(disconnect=lambda: noop("pool")))
    return host


def test_forget_tears_down_a_connected_host_and_the_next_get_re_checks_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = host_registry.HostRegistry(lambda: None)
    host = _fake_host()
    registry._hosts["studio"] = host
    registry._records["studio"] = object()
    disabled = SimpleNamespace(is_local=False, kind="ssh", enabled=False, probe_state="ok",
                               tmux_path="/t", login_shell="/z", key="studio")
    monkeypatch.setattr(registry, "_read_record", lambda _key: disabled)

    async def scenario() -> None:
        assert await registry.get("studio") is host
        await registry.forget("studio")
        assert host.calls == ["close", "channel", "pool"]
        assert "studio" not in registry._hosts and "studio" not in registry._records
        with pytest.raises(host_registry.HostUnavailable) as caught:
            await registry.get("studio")
        assert caught.value.code == "host_disabled"
        await registry.forget("never-connected")

    asyncio.run(scenario())


def test_a_sqlite_error_during_readopt_is_retried_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    async def get(_key: str) -> Any:
        return object()

    async def readopt_on(_manager: Any, _host: Any) -> dict:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"outcome": "ran", "held": []}

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(remote_readopt, "readopt_on", readopt_on)
    monkeypatch.setattr(remote_readopt.asyncio, "sleep", no_sleep)
    manager = SimpleNamespace(hosts=SimpleNamespace(get=get))
    report = asyncio.run(remote_readopt.readopt_host(manager, "studio", delay=lambda _a: 0.0))
    assert report["outcome"] == "ran" and attempts["n"] == 2


def test_one_hosts_crash_does_not_hide_the_others_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    async def readopt_host(_manager: Any, key: str, **_o: Any) -> dict:
        if key == "bad":
            raise KeyError("boom")
        return {"outcome": "ran"}

    monkeypatch.setattr(remote_readopt, "readopt_host", readopt_host)
    monkeypatch.setattr(remote_readopt, "open_remote_hosts", lambda _c: ["good", "bad"])
    manager = SimpleNamespace(_datastore_connection=lambda: None)
    reports = asyncio.run(remote_readopt.readopt_remote_hosts(manager))
    assert reports["good"] == {"outcome": "ran"} and reports["bad"]["outcome"] == "failed"


def _bind_world(monkeypatch: pytest.MonkeyPatch, writes: list) -> tuple:
    backend = SimpleNamespace(host=object(), host_key="studio", tmux_session="t1", socket_name="s")
    manager = SimpleNamespace(_registry=SimpleNamespace(backends={"ses_1": backend}))
    files = SimpleNamespace(bound={})
    monkeypatch.setattr(remote_resume, "is_remote_backend", lambda _b: True)
    import src.core.hosts.remote_claude_files as claude_files

    monkeypatch.setattr(claude_files, "files_for", lambda _host: files)
    monkeypatch.setattr(remote_resume, "_bind_write", lambda *_a: writes.pop(0))
    evidence = SimpleNamespace(agent_family="claude", identity=("x", "y", 5),
                               registry=SimpleNamespace(known=True, session_uuid="uuid-1", stale_cause=None))
    return manager, evidence, files


def test_a_failed_bind_write_is_retried_on_the_next_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, evidence, files = _bind_world(monkeypatch, [None, 1])
    assert remote_resume.bind_conversation(manager, "ses_1", evidence) is None
    assert files.bound == {}, "a failed write must not be remembered as bound"
    assert remote_resume.bind_conversation(manager, "ses_1", evidence) == "uuid-1"
    assert files.bound == {("t1", 5): "uuid-1"}


def test_bind_write_says_none_on_a_database_error() -> None:
    def broken() -> Any:
        raise sqlite3.OperationalError("database is locked")

    manager = SimpleNamespace(_writable_datastore_connection=broken)
    backend = SimpleNamespace(host_key="studio", socket_name="s", tmux_session="t1")
    assert remote_resume._bind_write(manager, backend, 5, "uuid-1", False) is None




def _ident(conversation: str) -> SessionIdentity:
    return SessionIdentity(row_id=1, session_uuid="u", tmux_name="t", tmux_epoch=1, title=None, conversation=conversation,
                           agent_family="claude", working_dir="/w", host_key="local", lifecycle="stopped", archived_at=None)


def test_a_wildcard_conversation_id_never_reaches_a_glob(tmp_path: Any) -> None:
    from src.core.inventory.identity import safe_conversation

    home = tmp_path / "claude"
    (home / "projects" / "-p").mkdir(parents=True)
    (home / "projects" / "-p" / "other-conversation.jsonl").write_text("{}\n")
    arts, _ = file_trace.trace(_ident("*"), homes=[home], codex=tmp_path / "codex")
    assert arts == [], "an unsafe primary id must trace nothing, or it would mark every transcript DELETE"
    assert safe_conversation("*") is None and safe_conversation("5f0c2a9e-1111") == "5f0c2a9e-1111"
    assert safe_conversation("100%_match") is None


def test_the_db_tracer_builds_no_like_from_an_unsafe_id() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE transcript_archives (id INTEGER PRIMARY KEY, root_session_id INT, "
                 "claude_session_uuid TEXT, source_path TEXT)")
    conn.execute("INSERT INTO transcript_archives (root_session_id, claude_session_uuid, source_path) "
                 "VALUES (99, 'x', '/a/other-conversation.jsonl')")
    assert db_trace._archive_ids(conn, _ident("%")) == []
    assert db_trace._archive_ids(conn, _ident("5f0c2a9e-1111")) == []




def test_the_codex_server_args_are_found_by_key_not_by_position() -> None:
    from src.config import mcp_launch
    from src.core.launch_profiles.resolve import _split_codex_server_args

    mcp = mcp_launch.codex_args("http://x")
    endpoint = ["-c", 'model_provider="p"']
    server, rest = _split_codex_server_args(mcp + endpoint + ["--no-alt-screen"])
    assert server == tuple(mcp + endpoint) and rest == ["--no-alt-screen"]
    tampered = list(mcp)
    tampered[3] = "model=o3"
    assert _split_codex_server_args(tampered)[0] == ()
    assert _split_codex_server_args(["--x"]) == ((), ["--x"])


def test_a_restart_record_is_built_without_reading_a_keychain_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.launch_profiles import create_seam, restart_seam
    from src.core.launch_profiles.plan import LaunchDisplay, LaunchPlan

    plan = LaunchPlan(command="c", argv_tail=(), env_set=(), env_unset=(), secret_refs=(("KEY", "ref"),),
                      display=LaunchDisplay(label="l", harness="codex", account="follow_active", model="m",
                                            permissions="default", endpoint="", key_hint=""),
                      digest="d", purpose="pane")

    async def materialize(_plan: Any) -> dict:
        raise AssertionError("the Keychain was read to build a record")

    monkeypatch.setattr(create_seam, "materialize", materialize)
    monkeypatch.setattr(create_seam, "recorded_account_id", lambda _h, _a: None)
    monkeypatch.setattr(create_seam, "launch_record_json", lambda p, account: json.dumps({"digest": p.digest, "a": account}))

    class Settings:
        def pane_launch_command(self, _agent: str, *, model: Any, extra_args: Any, plan_sink: list) -> str:
            plan_sink.append(plan)
            return "cmd"

    replayed = asyncio.run(restart_seam.resolve_replay(Settings(), "codex", model=None, extra_args=[], record_only=True))
    assert replayed is not None and json.loads(replayed.record or "{}")["digest"] == "d" and replayed.staged == {}




def test_one_panes_unexpected_error_is_that_panes_failed_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.layouts import broadcast, store

    class Backend:
        def __init__(self, fail: Exception | None) -> None:
            self.fail, self.sent = fail, []

        def is_alive(self) -> bool:
            return True

        async def paste_and_submit(self, text: str) -> None:
            if self.fail:
                raise self.fail
            self.sent.append(text)

    backends = {"sa": Backend(ValueError("odd")), "sb": Backend(None)}
    members = [SimpleNamespace(session_row_id=i, session_uuid=f"u{i}", position=i, broadcast=True) for i in (1, 2)]
    layout = SimpleNamespace(layout_uuid="L", members=members)
    infos = [SimpleNamespace(session_row_id=i, session=SimpleNamespace(id=f"s{c}"), activity_status="idle", startup_gate="ready")
             for i, c in ((1, "a"), (2, "b"))]
    outcomes = asyncio.run(broadcast.broadcast(layout, "ls", infos=infos, backend_for=backends.get))
    assert [(o.status, o.code) for o in outcomes] == [(broadcast.FAILED, "send_failed"), (broadcast.SENT, None)]
    assert backends["sb"].sent == ["ls"], "the other pane still got its line"
    assert store is not None




def test_a_purge_names_a_swarm_agent_and_a_foreign_key_instead_of_raising() -> None:
    from src.core.library_cleanup import sessions
    from src.core.library_cleanup.errors import CleanupRefused

    def world() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT, archived_at TEXT, "
                     "lifecycle TEXT, parent_session_id INT)")
        conn.execute("INSERT INTO sessions VALUES (1, 'u1', '2026-01-01', 'stopped', NULL)")
        return conn

    conn = world()
    conn.execute("CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, session_row_id INT REFERENCES sessions(id))")
    conn.execute("INSERT INTO swarm_agents (session_row_id) VALUES (1)")
    with pytest.raises(CleanupRefused) as swarm:
        sessions.purge_session(conn, "u1")
    assert swarm.value.code == sessions.REFUSE_SWARM_AGENT

    other = world()
    other.execute("CREATE TABLE junk (id INTEGER PRIMARY KEY, session_row_id INT REFERENCES sessions(id))")
    other.execute("INSERT INTO junk (session_row_id) VALUES (1)")
    with pytest.raises(CleanupRefused) as unknown:
        sessions.purge_session(other, "u1")
    assert unknown.value.code == sessions.REFUSE_REFERENCED
    assert other.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1, "the refusal rolled back"




def _memory_conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:", isolation_level=None)


def test_after_commit_runs_after_the_commit_and_never_after_a_rollback() -> None:
    conn = _memory_conn()
    conn.execute("CREATE TABLE t (a)")
    seen: List[str] = []
    with core_db.transaction(conn):
        core_db.after_commit(conn, lambda: seen.append(f"fired, in_tx={conn.in_transaction}"))
        assert seen == []
    assert seen == ["fired, in_tx=False"]
    with pytest.raises(RuntimeError):
        with core_db.transaction(conn):
            core_db.after_commit(conn, lambda: seen.append("ghost"))
            raise RuntimeError("rolled back")
    assert seen == ["fired, in_tx=False"]
    core_db.after_commit(conn, lambda: seen.append("immediate"))
    assert seen[-1] == "immediate" and core_db._AFTER_COMMIT == {}


def test_a_rolled_back_lineage_write_announces_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.lineage import graph
    from tests.s7_helpers import migrated_connection
    import tempfile
    from pathlib import Path

    announced: List[int] = []
    monkeypatch.setattr(graph.timeline_push, "announce", lambda: announced.append(1))
    with tempfile.TemporaryDirectory() as tmp:
        conn = migrated_connection(Path(tmp))
        with pytest.raises(RuntimeError):
            with core_db.transaction(conn):
                graph.add_edge(conn, "conversation", "a", "session", "s", "clear")
                raise RuntimeError("rollback")
        assert announced == []
        with core_db.transaction(conn):
            graph.add_edge(conn, "conversation", "a", "session", "s", "clear")
            assert announced == [], "not before the commit"
        assert announced == [1]
        conn.close()




def test_a_programming_error_in_the_seed_row_read_is_logged_loudly() -> None:
    from src.core import listing_attention

    class Index:
        complete = True

        def seed_row(self, _name: Any, _epoch: Any) -> dict:
            raise KeyError("renamed_column")

    with structlog.testing.capture_logs() as logs:
        assert listing_attention.conversation_for_instance(Index(), "t", 1) == (None, None)
    assert any(e["event"] == "listing_attention_seed_row_bug" and e["log_level"] == "error"
               and e["error_type"] == "KeyError" for e in logs)
    assert listing_attention._READ_ERRORS == (OSError, ValueError)




def test_a_port_already_tracked_costs_no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core import local_servers as ls

    tracker = ls.LocalServersTracker()
    now = utc_now()
    tracker._state["s1"] = {5173: ls.LocalServerInfo(port=5173, url="u", first_seen=now, last_seen=now)}
    tracker._log_monitor = SimpleNamespace(pattern_detector=SimpleNamespace(extract_port=lambda _t: 5173))
    tracker._session_manager = object()

    def owner(*_a: Any) -> str:
        raise AssertionError("find_port_owner shells out to lsof/tmux/ps")

    monkeypatch.setattr(ls, "find_port_owner", owner)
    asyncio.run(tracker._on_pattern_match(SimpleNamespace(matched_text="localhost:5173")))


def test_pattern_tasks_are_kept_until_they_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core import local_servers as ls

    tracker = ls.LocalServersTracker()

    async def scenario() -> None:
        gate = asyncio.Event()

        async def slow(_match: Any) -> None:
            await gate.wait()

        monkeypatch.setattr(tracker, "_on_pattern_match", slow)
        tracker._spawn_pattern_task(SimpleNamespace())
        assert len(tracker._pattern_tasks) == 1
        gate.set()
        await asyncio.sleep(0.01)
        assert tracker._pattern_tasks == set()

    asyncio.run(scenario())




def _body(choice: dict) -> Any:
    from src.models.dialogs import DialogAnswerRequest

    return DialogAnswerRequest(fingerprint="a" * 64, choice=choice)


def test_a_typed_dialog_answer_shows_its_text_and_two_texts_do_not_dedupe() -> None:
    from src.core.mcp import dialog_tools
    from src.core.mcp.approvals import display

    one, two = _body({"other": "run the migration"}), _body({"other": "drop the table!"})
    assert dialog_tools._shown(one)["choice"] == {"other": "run the migration"}
    assert dialog_tools._choice_digest(one) != dialog_tools._choice_digest(two)
    typed = {"other": "run the migration\nFAKE ROW"}
    block = display.build("session_dialog_answer", {"target": "u1", "choice": typed}, "api", "answer",
                          plain="", confirm_text="", live=False)
    assert block["consequences"][0] == {"key": "answers_with", "params": {"choice": "run the migration FAKE ROW"}}


def test_a_dialog_answer_text_is_redacted_on_the_card() -> None:
    from src.core.mcp import dialog_tools

    shown = dialog_tools._shown(_body({"other": "token sk-ant-api03-" + "A" * 40}))["choice"]["other"]
    assert "A" * 40 not in shown


def test_a_failed_bulk_colour_write_names_the_rows_that_already_landed(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from src.api import projects_routes
    from src.core.mcp import project_color_tools, pending
    from src.core.mcp.caller import AgentCaller
    from src.core.mcp.common import ToolError

    names = {1: "alpha", 2: "beta"}

    async def names_by_id() -> dict:
        return names

    done: List[Any] = []

    async def update_project(name: str, request: Any) -> Any:
        if name == "beta":
            raise HTTPException(status_code=409, detail="name collision")
        done.append(name)
        return SimpleNamespace(id=1, name=name, color=request.color)

    captured: dict = {}

    async def park(_m: Any, _c: Any, _s: str, _t: str, _action: str, _summary: str, _shown: dict, run: Any, **_k: Any) -> dict:
        captured["run"] = run
        return {}

    import src.core.mcp.project_tools as project_tools
    import src.core.mcp.write_tools as write_tools

    monkeypatch.setattr(project_tools, "_names_by_id", names_by_id)
    monkeypatch.setattr(projects_routes, "update_project", update_project)
    monkeypatch.setattr(write_tools, "park", park)
    caller = AgentCaller("ses_a", "cloude_a", "ses_a")
    asyncio.run(project_color_tools.project_color_set(None, caller, {"colors": {"alpha": "#aabbcc", "beta": "#112233"}}))
    with pytest.raises(ToolError) as caught:
        asyncio.run(captured["run"](True))
    assert "already changed: 1 (\"alpha\")" in str(caught.value) and "project id 2" in str(caught.value)
    assert done == ["alpha"] and pending is not None
