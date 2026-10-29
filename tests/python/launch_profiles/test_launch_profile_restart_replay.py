
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.config.agents import AgentsConfig
from src.config.byoai import ConnectionConfig
from src.config.launch_profiles import LaunchProfile
from src.config.session import SessionConfig
from src.core.agent_wrappers import AgentWrapper
from src.core.byoai.keys import KeyStore
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.session_manager import SessionManager
from src.core.session_resume_target import CONVERSATION_RESUMED, ResumeTarget
from src.core.tmux_backend import TmuxBackend

KEY = "sk-fake-0123456789abcdef"
CONVERSATION = "11111111-2222-4333-8444-555555555555"


class FakeBackend:

    def __init__(self, values):
        self.values = dict(values)

    def read(self, service, account):
        return self.values.get(account)


def _profile(pid: str, **kw) -> LaunchProfile:
    return LaunchProfile.model_validate({"id": pid, "harness": "claude", "label": pid, **kw})


@pytest.fixture
def env(tmp_path, monkeypatch, tmux_test_socket):
    state_dir, log_dir = tmp_path / "state", tmp_path / "logs"
    for d in (state_dir, log_dir):
        d.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    ensure_db_migrated(state_dir)
    connection = ConnectionConfig(id="or", preset="openrouter", label="or", base_url="https://openrouter.ai/api/v1",
                                  key_host="https://openrouter.ai", key_hint="cdef")
    profiles = [
        _profile("claude-ask", default=True, model={"mode": "ask"}),
        _profile("claude-or", endpoint={"mode": "connection", "connection_id": "or"}, model={"mode": "fixed", "value": "m-1"}),
    ]

    def _auth(self):
        return SimpleNamespace(
            agents=AgentsConfig(wrappers=[AgentWrapper(id=p.id, label=p.id, script="claude") for p in profiles]),
            session=SessionConfig(tmux_socket_name=tmux_test_socket), mcp=SimpleNamespace(channels=False, enabled=False),
            launch_profiles=SimpleNamespace(profiles=list(profiles)), byoai=SimpleNamespace(connections=[connection]))

    monkeypatch.setattr(type(settings), "load_auth_config", _auth)
    monkeypatch.setattr("src.core.launch_profiles.secrets.KeyStore", lambda: KeyStore(backend=FakeBackend({"or": KEY})))
    seen: dict = {"respawns": []}
    real_start, real_respawn = TmuxBackend.start, TmuxBackend.respawn

    async def start_spy(self, command=None, env=None, **kw):
        return await real_start(self, command="sleep 30", env=env, **kw)

    async def respawn_spy(self, *, agent_command=None, spawn_env=None, **kw):
        seen["respawns"].append({"command": agent_command, "env": dict(spawn_env or {})})
        return await real_respawn(self, agent_command="sleep 30" if agent_command else None, spawn_env=spawn_env, **kw)

    monkeypatch.setattr(TmuxBackend, "start", start_spy)
    monkeypatch.setattr(TmuxBackend, "respawn", respawn_spy)
    return SimpleNamespace(state_dir=state_dir, seen=seen, tmp=tmp_path, socket=tmux_test_socket, profiles=profiles)


async def _create(env, agent_type, model=None):
    work = env.tmp / f"wd{uuid.uuid4().hex[:6]}"
    work.mkdir()
    token = uuid.uuid4().hex[:8]
    mgr = SessionManager()
    session = await mgr.create_session(session_id=f"ses_{token}", working_dir=str(work), auto_start_claude=True,
                                       project_name=f"lp{token}", agent_type=agent_type, model=model)
    mgr._resume_target_for_tmux_name = lambda name, socket: ResumeTarget(
        outcome=CONVERSATION_RESUMED, claude_session_uuid=CONVERSATION, detail="resumed")
    return mgr, session


def _row(env, session):
    with closing(connect(db_path_for(env.state_dir))) as handle:
        return handle.execute("SELECT agent_type, launch_record FROM sessions WHERE tmux_name = ?",
                              (session.tmux_session,)).fetchone()


def _set_record(env, session, record):
    with closing(connect(db_path_for(env.state_dir))) as handle:
        handle.execute("UPDATE sessions SET launch_record = ? WHERE tmux_name = ?", (record, session.tmux_session))


@pytest.mark.asyncio
async def test_restart_replays_the_recorded_model_and_resumes_once(env):
    mgr, session = await _create(env, "claude-ask", model="opus-x")
    try:
        result = await mgr.respawn_session(session.tmux_session, socket_name=env.socket, live_restart_confirmed=True)
        assert result["ok"] and result["kind"] == "agent"
        command = env.seen["respawns"][-1]["command"]
        assert command.count("--resume") == 1 and CONVERSATION in command
        assert "--model" in command and "opus-x" in command
        record = json.loads(_row(env, session)["launch_record"])
        assert record["profile"] == "claude-ask" and record["purpose"] == "pane"
    finally:
        await mgr.destroy_session(session.id)


@pytest.mark.asyncio
async def test_restart_secret_reaches_the_env_write_only_and_the_record_follows_the_profile(env):
    mgr, session = await _create(env, "claude-or")
    try:
        env.profiles[1] = _profile("claude-or", endpoint={"mode": "connection", "connection_id": "or"},
                                   model={"mode": "fixed", "value": "m-2"})
        result = await mgr.respawn_session(session.tmux_session, socket_name=env.socket, live_restart_confirmed=True)
        assert result["ok"] and result["kind"] == "agent"
        sent = env.seen["respawns"][-1]
        assert sent["env"]["CARNIVORE_LAUNCH_SECRET_0"] == KEY
        assert KEY not in sent["command"] and "CARNIVORE_LAUNCH_SECRET_0" in sent["command"]
        assert "m-2" in sent["command"] and sent["command"].count("--resume") == 1
        row = _row(env, session)
        assert json.loads(row["launch_record"])["model"] == "m-2" and KEY not in row["launch_record"]
        shown = subprocess.run(["tmux", "-L", env.socket, "show-environment", "-t", f"={session.tmux_session}"],
                               capture_output=True, text=True, check=False).stdout
        assert KEY not in shown and "CARNIVORE_LAUNCH_SECRET_0=" not in shown
    finally:
        await mgr.destroy_session(session.id)


@pytest.mark.asyncio
async def test_a_deleted_profile_is_refused_by_name_and_nothing_is_respawned(env):
    mgr, session = await _create(env, "claude-or")
    try:
        del env.profiles[1]
        with pytest.raises(LaunchProfileNotFound) as refused:
            await mgr.respawn_session(session.tmux_session, socket_name=env.socket, live_restart_confirmed=True)
        assert refused.value.profile_id == "claude-or"
        assert refused.value.codes == ("wrapper_needed", "launch_profile_needed")
        assert env.seen["respawns"] == []
        preview = await mgr.restart_preview(session.tmux_session, socket_name=env.socket)
        assert preview.launch_display["missing_profile"] == "claude-or"
    finally:
        await mgr.destroy_session(session.id)


@pytest.mark.asyncio
async def test_a_legacy_row_without_a_record_restarts_as_before(env):
    mgr, session = await _create(env, "claude-ask", model="opus-x")
    try:
        _set_record(env, session, None)
        result = await mgr.respawn_session(session.tmux_session, socket_name=env.socket, live_restart_confirmed=True)
        assert result["ok"]
        sent = env.seen["respawns"][-1]
        assert sent["command"].count("--resume") == 1 and not any(k.startswith("CARNIVORE_LAUNCH_SECRET") for k in sent["env"])
        assert _row(env, session)["launch_record"] is None
        preview = await mgr.restart_preview(session.tmux_session, socket_name=env.socket)
        assert preview.launch_display is None
    finally:
        await mgr.destroy_session(session.id)


@pytest.mark.asyncio
async def test_a_restart_with_no_conversation_to_resume_still_replays(env):
    mgr, session = await _create(env, "claude-ask", model="opus-x")
    try:
        mgr._resume_target_for_tmux_name = lambda name, socket: ResumeTarget(outcome="none_recorded", claude_session_uuid=None, detail="none")
        result = await mgr.respawn_session(session.tmux_session, socket_name=env.socket, live_restart_confirmed=True)
        assert result["ok"]
        command = env.seen["respawns"][-1]["command"]
        assert "--resume" not in command and "opus-x" in command
        assert (await mgr.restart_preview(session.tmux_session, socket_name=env.socket)).launch_display["harness"] == "claude"
    finally:
        await mgr.destroy_session(session.id)
