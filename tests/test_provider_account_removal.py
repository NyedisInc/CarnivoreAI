
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.config import settings
from src.config.provider_accounts import managed_dir_for
from src.core.provider_ledger import poller, refresh_poke

ACCOUNTS_URL = "/api/v1/provider-ledger/accounts"

MANAGED_CLAUDE = {"name": "Claude 1", "provider": "claude", "managed": True}
MANAGED_CODEX = {"name": "Codex 1", "provider": "codex", "managed": True}


class FakeBackend:

    def __init__(self, alive: bool = True) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class FakeSidecars:

    def __init__(self) -> None:
        self.pending: dict = {}
        self.login_sessions: dict = {}

    def set_pending_login(self, session_id: str, account_id: str, device_auth: bool = False) -> None:
        self.pending[session_id] = account_id
        self.login_sessions[account_id] = session_id

    def login_session_for(self, account_id: str):
        return self.login_sessions.get(account_id)


class FakeManager:

    def __init__(self) -> None:
        self._registry = SimpleNamespace(sessions={}, backends={})
        self._sidecars = FakeSidecars()
        self.infos: list = []

    async def list_session_infos(self) -> list:
        return list(self.infos)

    def tmux_socket_name(self) -> str:
        from tests.socket_guard import TEST_SOCKET_NAME

        return TEST_SOCKET_NAME

    async def create_session(self, session_id: str, **kwargs):
        session = SimpleNamespace(
            id=session_id,
            tmux_session=f"cloude_{kwargs.get('project_name')}",
            working_dir=kwargs.get("working_dir"),
        )
        self._registry.sessions[session_id] = session
        self._registry.backends[session_id] = FakeBackend()
        return session


class LogoutRecorder:

    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.calls: list = []

    async def __call__(self, argv, env, **kwargs):
        self.calls.append({"argv": list(argv), "env": dict(env)})
        return refresh_poke.PokeOutcome(
            ran=True, exit_code=self.exit_code, timed_out=False, duration_seconds=0.1
        )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": [], "agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    settings._auth_config_cache = None

    forgotten: list = []
    monkeypatch.setattr(poller, "poll_soon", lambda account_id: None)
    monkeypatch.setattr(
        poller, "forget_account", lambda account_id: forgotten.append(account_id)
    )

    recorder = LogoutRecorder()
    monkeypatch.setattr(refresh_poke, "run_poke", recorder)
    monkeypatch.setattr(
        refresh_poke, "resolve_binary", lambda name: f"/fake/bin/{name}"
    )

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = FakeManager()
    with TestClient(app) as test_client:
        test_client.config_path = path
        test_client.home = tmp_path
        test_client.logout = recorder
        test_client.forgotten = forgotten
        test_client.manager = app.state.session_manager
        yield test_client
    settings._auth_config_cache = None


def add(client, account_id: str, body: dict) -> dict:
    answer = client.put(f"{ACCOUNTS_URL}/{account_id}", json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()


def stored_ids(path: Path) -> list:
    block = json.loads(path.read_text()).get("provider_accounts", {})
    return [row["id"] for row in block.get("accounts", [])]




def test_it_deletes_the_managed_profile_directory(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    directory = Path(managed_dir_for("claude1"))
    assert directory.is_dir()

    answer = client.delete(f"{ACCOUNTS_URL}/claude1")

    assert answer.status_code == 200
    assert not directory.exists()


def test_it_says_what_happened_to_the_login_and_the_directory(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)

    body = client.delete(f"{ACCOUNTS_URL}/claude1").json()

    assert body == {"removed": "claude1", "logout": "ok", "directory": "removed"}


def test_the_row_is_gone_too(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert stored_ids(client.config_path) == []


def test_the_logout_runs_the_providers_own_command(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert client.logout.calls[0]["argv"] == ["/fake/bin/claude", "auth", "logout"]


def test_the_logout_is_pointed_at_the_profile_being_retired(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    expected = managed_dir_for("claude1")

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert client.logout.calls[0]["env"]["CLAUDE_CONFIG_DIR"] == expected


def test_the_logout_child_carries_no_credential(client, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "must-not-be-spent")
    add(client, "claude1", MANAGED_CLAUDE)

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert "CLAUDE_CODE_OAUTH_REFRESH_TOKEN" not in client.logout.calls[0]["env"]


def test_a_managed_codex_row_runs_codex_logout(client) -> None:
    add(client, "codex1", MANAGED_CODEX)

    body = client.delete(f"{ACCOUNTS_URL}/codex1").json()

    assert client.logout.calls[0]["argv"] == ["/fake/bin/codex", "logout"]
    assert client.logout.calls[0]["env"]["CODEX_HOME"] == managed_dir_for("codex1")
    assert body["directory"] == "removed"


def test_the_logout_happens_before_the_directory_goes(client, monkeypatch) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    directory = Path(managed_dir_for("claude1"))
    seen: list = []

    async def watch(argv, env, **kwargs):
        seen.append(directory.is_dir())
        return refresh_poke.PokeOutcome(
            ran=True, exit_code=0, timed_out=False, duration_seconds=0.1
        )

    monkeypatch.setattr(refresh_poke, "run_poke", watch)

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert seen == [True]


def test_the_siblings_keep_their_own_directories(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    add(client, "claude2", {**MANAGED_CLAUDE, "name": "Claude 2"})

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert Path(managed_dir_for("claude2")).is_dir()
    assert stored_ids(client.config_path) == ["claude2"]


def test_the_poller_is_told_to_forget_the_account(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert client.forgotten == ["claude1"]




def test_a_failed_logout_still_deletes_the_directory(client, monkeypatch) -> None:
    monkeypatch.setattr(refresh_poke, "run_poke", LogoutRecorder(exit_code=1))
    add(client, "claude1", MANAGED_CLAUDE)

    body = client.delete(f"{ACCOUNTS_URL}/claude1").json()

    assert body["logout"] == "failed"
    assert body["directory"] == "removed"
    assert not Path(managed_dir_for("claude1")).exists()
    assert stored_ids(client.config_path) == []


def test_no_provider_binary_on_the_machine_still_removes_everything(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(refresh_poke, "resolve_binary", lambda name: None)
    add(client, "claude1", MANAGED_CLAUDE)

    body = client.delete(f"{ACCOUNTS_URL}/claude1").json()

    assert body["logout"] == "failed"
    assert body["directory"] == "removed"




def test_a_symlinked_profile_directory_is_refused_and_the_row_still_goes(
    client, tmp_path_factory
) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    directory = Path(managed_dir_for("claude1"))
    elsewhere = tmp_path_factory.mktemp("someone_elses")
    (elsewhere / "theirs.txt").write_text("not ours")
    directory.rmdir()
    directory.symlink_to(elsewhere)

    body = client.delete(f"{ACCOUNTS_URL}/claude1").json()

    assert body["directory"] == "refused"
    assert (elsewhere / "theirs.txt").exists()
    assert stored_ids(client.config_path) == []


def test_a_directory_the_user_already_deleted_is_absent(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    Path(managed_dir_for("claude1")).rmdir()

    body = client.delete(f"{ACCOUNTS_URL}/claude1").json()

    assert body["directory"] == "absent"
    assert stored_ids(client.config_path) == []




def test_a_live_login_pane_refuses_the_removal(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    assert client.post(f"{ACCOUNTS_URL}/claude1/login").status_code == 200

    answer = client.delete(f"{ACCOUNTS_URL}/claude1")

    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "login_in_progress"


def test_a_refused_removal_removes_nothing_at_all(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")

    client.delete(f"{ACCOUNTS_URL}/claude1")

    assert Path(managed_dir_for("claude1")).is_dir()
    assert stored_ids(client.config_path) == ["claude1"]
    assert client.logout.calls == []


def test_a_login_pane_that_died_does_not_block_it(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    for session_id in list(client.manager._registry.backends):
        client.manager._registry.backends[session_id] = FakeBackend(alive=False)

    answer = client.delete(f"{ACCOUNTS_URL}/claude1")

    assert answer.status_code == 200
    assert not Path(managed_dir_for("claude1")).exists()




def test_an_unmanaged_row_keeps_its_directory(client) -> None:
    theirs = client.home / ".claude-work"
    theirs.mkdir()
    (theirs / ".credentials.json").write_text("{}")
    add(
        client,
        "work",
        {
            "name": "Work",
            "provider": "claude",
            "claude_config_dir": str(theirs),
            "managed": False,
        },
    )

    body = client.delete(f"{ACCOUNTS_URL}/work").json()

    assert body == {"removed": "work", "logout": "skipped", "directory": "kept"}
    assert (theirs / ".credentials.json").exists()


def test_an_unmanaged_row_is_never_signed_out(client) -> None:
    theirs = client.home / ".claude-work"
    theirs.mkdir()
    add(
        client,
        "work",
        {
            "name": "Work",
            "provider": "claude",
            "claude_config_dir": str(theirs),
            "managed": False,
        },
    )

    client.delete(f"{ACCOUNTS_URL}/work")

    assert client.logout.calls == []


def test_an_unmanaged_row_is_still_removed(client) -> None:
    theirs = client.home / ".claude-work"
    theirs.mkdir()
    add(
        client,
        "work",
        {
            "name": "Work",
            "provider": "claude",
            "claude_config_dir": str(theirs),
            "managed": False,
        },
    )

    client.delete(f"{ACCOUNTS_URL}/work")

    assert stored_ids(client.config_path) == []




def test_an_unknown_id_is_a_404(client) -> None:
    answer = client.delete(f"{ACCOUNTS_URL}/never-configured")

    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "not_found"


def test_an_unknown_id_deletes_no_directory_and_runs_no_logout(client) -> None:
    (client.home / ".carnivore" / "accounts" / "never-configured").mkdir(parents=True)

    client.delete(f"{ACCOUNTS_URL}/never-configured")

    assert (client.home / ".carnivore/accounts/never-configured").is_dir()
    assert client.logout.calls == []




def _running_claude(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        tmux_session=name, agent_family="claude", activity_status="idle",
        label=None, session=SimpleNamespace(id=f"id_{name}"),
    )


def test_an_account_a_running_session_uses_is_refused(client, monkeypatch) -> None:
    from src.core.account_switch import pane_account

    add(client, "claude1", MANAGED_CLAUDE)
    profile = Path(managed_dir_for("claude1"))
    client.manager.infos = [_running_claude("cloude_busy")]

    async def on_profile(socket, name, variable):
        return pane_account.PaneProfile(readable=True, value=str(profile))

    monkeypatch.setattr(pane_account, "read_pane_profile", on_profile)
    response = client.delete(f"{ACCOUNTS_URL}/claude1")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_in_use"
    assert profile.is_dir()


def test_a_session_on_the_default_login_does_not_block_it(client, monkeypatch) -> None:
    from src.core.account_switch import pane_account

    add(client, "claude1", MANAGED_CLAUDE)
    client.manager.infos = [_running_claude("cloude_elsewhere")]

    async def default_login(socket, name, variable):
        return pane_account.PaneProfile(readable=True, value=None)

    monkeypatch.setattr(pane_account, "read_pane_profile", default_login)
    assert client.delete(f"{ACCOUNTS_URL}/claude1").status_code == 200


def test_removing_the_active_account_clears_its_switch_pointer(client) -> None:
    from src.core.account_switch import store

    add(client, "claude1", MANAGED_CLAUDE)
    store.set_active(Path(settings.auth_config_file), "claude", "claude1")
    assert client.delete(f"{ACCOUNTS_URL}/claude1").status_code == 200
    assert store.read_switch(Path(settings.auth_config_file)).active_claude is None
