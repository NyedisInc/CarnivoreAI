
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
from src.core.launch_profiles import create_seam
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.launch_profiles.secrets import KeyUnavailable
from src.core.session_manager import SessionManager
from src.core.tmux_backend import TmuxBackend

KEY = "sk-fake-0123456789abcdef"


class FakeBackend:

    def __init__(self, values):
        self.values = dict(values)

    def read(self, service, account):
        return self.values.get(account)


def _profile(pid: str, **kw) -> LaunchProfile:
    return LaunchProfile.model_validate({
        "id": pid, "harness": "claude", "label": pid, "endpoint": {"mode": "connection", "connection_id": "or"},
        "model": {"mode": "fixed", "value": "m-1"}, **kw})


@pytest.fixture
def env(tmp_path, monkeypatch, tmux_test_socket):
    state_dir = tmp_path / "state"
    log_dir = tmp_path / "logs"
    for d in (state_dir, log_dir):
        d.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    ensure_db_migrated(state_dir)
    connection = ConnectionConfig(id="or", preset="openrouter", label="or", base_url="https://openrouter.ai/api/v1",
                                  key_host="https://openrouter.ai", key_hint="cdef")

    def _auth(self):
        return SimpleNamespace(
            agents=AgentsConfig(wrappers=[AgentWrapper(id="claude-or", label="or", script="claude")]), session=SessionConfig(tmux_socket_name=tmux_test_socket), mcp=SimpleNamespace(channels=False, enabled=False, beast_mode=False, beast_grid={}, beast_trust_scope="projects"),
            launch_profiles=SimpleNamespace(profiles=[_profile("claude-plain", default=True, endpoint={"mode": "native"}),
                                                      _profile("claude-or")]),
            byoai=SimpleNamespace(connections=[connection]),
        )

    monkeypatch.setattr(type(settings), "load_auth_config", _auth)
    store = KeyStore(backend=FakeBackend({"or": KEY}))
    monkeypatch.setattr("src.core.launch_profiles.secrets.KeyStore", lambda: store)
    seen: dict = {}
    real_start = TmuxBackend.start

    async def spy(self, command=None, env=None, **kw):
        seen.update(command=command, env=dict(env or {}))
        return await real_start(self, command="sleep 30", env=env, **kw)

    monkeypatch.setattr(TmuxBackend, "start", spy)
    return SimpleNamespace(state_dir=state_dir, seen=seen, tmp=tmp_path, keys=store, socket=tmux_test_socket)


async def _create(env, agent_type):
    work = env.tmp / f"wd{uuid.uuid4().hex[:6]}"
    work.mkdir()
    token = uuid.uuid4().hex[:8]
    mgr = SessionManager()
    session = await mgr.create_session(
        session_id=f"ses_{token}", working_dir=str(work), auto_start_claude=True,
        project_name=f"lp{token}", agent_type=agent_type)
    return mgr, session


def _row(env, session):
    with closing(connect(db_path_for(env.state_dir))) as handle:
        return handle.execute("SELECT agent_type, launch_record FROM sessions WHERE tmux_name = ?",
                              (session.tmux_session,)).fetchone()


@pytest.mark.asyncio
async def test_endpoint_profile_secret_rides_the_start_env_only_and_the_row_holds_the_record(env):
    mgr, session = await _create(env, "claude-or")
    try:
        staged = env.seen["env"]["CARNIVORE_LAUNCH_SECRET_0"]
        assert staged == KEY
        assert KEY not in env.seen["command"] and "CARNIVORE_LAUNCH_SECRET_0" in env.seen["command"]
        row = _row(env, session)
        assert row["agent_type"] == "claude-or"
        record = json.loads(row["launch_record"])
        assert set(record) == {"profile", "digest", "harness", "account", "endpoint", "model", "permissions", "purpose"}
        assert record["profile"] == "claude-or" and record["harness"] == "claude" and record["model"] == "m-1"
        assert record["endpoint"] == {"connection_id": "or", "label": "or"}
        assert record["account"]["mode"] == "follow_active" and record["purpose"] == "pane"
        assert KEY not in row["launch_record"]
        shown = subprocess.run(["tmux", "-L", env.socket, "show-environment", "-t", f"={session.tmux_session}"],
                               capture_output=True, text=True, check=False).stdout
        assert "CARNIVORE_HOOK_TOKEN" in shown and "CARNIVORE_LAUNCH_SECRET_0=" not in shown and KEY not in shown
    finally:
        await mgr.destroy_session(session.id)


@pytest.mark.asyncio
async def test_a_bare_family_still_creates_and_a_missing_key_refuses_the_create(env, monkeypatch):
    mgr, session = await _create(env, "claude")
    try:
        assert "CARNIVORE_LAUNCH_SECRET_0" not in env.seen["env"]
        assert json.loads(_row(env, session)["launch_record"])["endpoint"] is None
    finally:
        await mgr.destroy_session(session.id)
    monkeypatch.setattr("src.core.launch_profiles.secrets.KeyStore", lambda: KeyStore(backend=FakeBackend({})))
    with pytest.raises(KeyUnavailable):
        await _create(env, "claude-or")


def test_an_explicit_missing_pick_is_refused_with_both_codes(env):
    create_seam.check_explicit_pick(settings, "claude")
    create_seam.check_explicit_pick(settings, None)
    create_seam.check_explicit_pick(settings, "claude-or")
    with pytest.raises(LaunchProfileNotFound) as refused:
        create_seam.check_explicit_pick(settings, "nope-profile")
    assert refused.value.codes == ("wrapper_needed", "launch_profile_needed")
    assert "claude-or" in refused.value.available


@pytest.mark.asyncio
async def test_create_hands_the_chosen_account_to_the_launch_record(env, monkeypatch):
    asked: list = []
    real_prepare = create_seam.prepare

    async def spy(plan, *args, **kw):
        asked.append(kw.get("account_id"))
        return await real_prepare(plan, *args, **kw)

    monkeypatch.setattr(create_seam, "prepare", spy)
    from src.config import provider_accounts
    from src.core.account_switch import active, session_pin, shared_links
    monkeypatch.setattr(session_pin, "all_accounts", lambda path: [])
    monkeypatch.setattr(active, "find_account", lambda accounts, account_id, provider: SimpleNamespace(provider=provider, id=account_id))
    monkeypatch.setattr(provider_accounts, "profile_dir_for", lambda account: "/profiles/work")
    monkeypatch.setattr(shared_links, "is_default_profile", lambda provider, profile_dir: False)
    work = env.tmp / "wd_acct"
    work.mkdir()
    mgr = SessionManager()
    session = await mgr.create_session(session_id="ses_acct1", working_dir=str(work), auto_start_claude=True,
                                       project_name="lpacct", agent_type="claude-or", claude_account="work")
    try:
        assert asked == ["work"]
        stored = json.loads(_row(env, session)["launch_record"])
        assert stored["account"]["id"] == "work"
    finally:
        await mgr.destroy_session(session.id)
