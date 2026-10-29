
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plr2_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plr2_logs_"))
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
from src.core.provider_ledger import poller

ACCOUNTS_URL = "/api/v1/provider-ledger/accounts"

MANAGED_CLAUDE = {"name": "Claude 1", "provider": "claude", "managed": True}
MANAGED_CODEX = {"name": "Codex 1", "provider": "codex", "managed": True}
HAND_WRITTEN = {
    "name": "Work",
    "provider": "claude",
    "claude_config_dir": "~/.claude-work",
    "managed": False,
}


class FakeBackend:

    def __init__(self, alive: bool = True) -> None:
        self._alive = alive
        self.written: list = []

    def is_alive(self) -> bool:
        return self._alive

    async def write(self, payload: bytes) -> None:
        self.written.append(payload)


class FakeRegistry:

    def __init__(self) -> None:
        self.sessions: dict = {}
        self.backends: dict = {}


class FakeSidecars:

    def __init__(self) -> None:
        self.pending: dict = {}
        self.device: dict = {}
        self.login_sessions: dict = {}

    def set_pending_login(
        self, session_id: str, account_id: str, device_auth: bool = False
    ) -> None:
        self.pending[session_id] = account_id
        self.device[session_id] = device_auth
        self.login_sessions[account_id] = session_id

    def login_session_for(self, account_id: str):
        return self.login_sessions.get(account_id)


class FakeManager:

    def __init__(self) -> None:
        self._registry = FakeRegistry()
        self._sidecars = FakeSidecars()
        self.calls: list = []
        self.counter = 0

    async def create_session(self, session_id: str, **kwargs):
        self.counter += 1
        working_dir = kwargs.get("working_dir")
        self.calls.append(
            {
                "session_id": session_id,
                "dir_existed_at_spawn": bool(
                    working_dir and Path(working_dir).is_dir()
                ),
                **kwargs,
            }
        )
        name = f"cloude_{kwargs.get('project_name')}"
        session = SimpleNamespace(
            id=session_id, tmux_session=name, working_dir=working_dir
        )
        self._registry.sessions[session_id] = session
        self._registry.backends[session_id] = FakeBackend()
        return session


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": [], "agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    settings._auth_config_cache = None

    polled: list = []
    monkeypatch.setattr(
        poller, "poll_soon", lambda account_id: polled.append(account_id)
    )

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = FakeManager()
    with TestClient(app) as test_client:
        test_client.config_path = path
        test_client.manager = app.state.session_manager
        test_client.polled = polled
        test_client.home = tmp_path
        yield test_client
    settings._auth_config_cache = None


def add(client, account_id: str, body: dict) -> dict:
    answer = client.put(f"{ACCOUNTS_URL}/{account_id}", json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()




def test_an_unknown_account_is_a_404(client) -> None:
    answer = client.post(f"{ACCOUNTS_URL}/nobody/login")
    assert answer.status_code == 404
    assert answer.json()["detail"]["code"] == "not_found"


def test_an_unknown_account_spawns_nothing(client) -> None:
    client.post(f"{ACCOUNTS_URL}/nobody/login")
    assert client.manager.calls == []




def test_it_answers_the_session_id_and_the_tmux_name(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    answer = client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert answer.status_code == 200
    body = answer.json()
    assert set(body) == {"session_id", "tmux_session", "device_auth"}
    assert body["tmux_session"] == "cloude_login_claude1"


def test_the_profile_directory_is_created_and_is_0700(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    path = Path(managed_dir_for("claude1"))
    assert path.is_dir()
    assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_the_directory_exists_before_anything_is_spawned(client) -> None:
    add(client, "codex1", MANAGED_CODEX)
    client.post(f"{ACCOUNTS_URL}/codex1/login")
    assert client.manager.calls[0]["dir_existed_at_spawn"] is True


def test_the_one_env_pair_is_the_claude_config_dir(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert client.manager.calls[0]["extra_env"] == {
        "CLAUDE_CONFIG_DIR": managed_dir_for("claude1")
    }


def test_a_codex_account_gets_codex_home_instead(client) -> None:
    add(client, "codex1", MANAGED_CODEX)
    client.post(f"{ACCOUNTS_URL}/codex1/login")
    assert client.manager.calls[0]["extra_env"] == {
        "CODEX_HOME": managed_dir_for("codex1")
    }


def test_the_pane_runs_in_the_profile_directory(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert client.manager.calls[0]["working_dir"] == managed_dir_for("claude1")


def test_the_pane_is_a_plain_shell_and_not_an_agent(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert client.manager.calls[0]["auto_start_claude"] is False


def test_the_session_is_named_for_the_account(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert client.manager.calls[0]["project_name"] == "login_claude1"


def test_an_account_id_is_what_waits_on_the_attach_not_a_command(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    body = client.post(f"{ACCOUNTS_URL}/claude1/login").json()
    assert client.manager._sidecars.pending == {body["session_id"]: "claude1"}


def test_the_ledger_is_asked_to_re_read_that_account_soon(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.polled.clear()
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert "claude1" in client.polled




def test_an_unmanaged_row_logs_into_the_path_it_names(client) -> None:
    add(client, "work", HAND_WRITTEN)
    client.post(f"{ACCOUNTS_URL}/work/login")
    assert client.manager.calls[0]["extra_env"] == {
        "CLAUDE_CONFIG_DIR": os.path.realpath(
            os.path.expanduser("~/.claude-work")
        )
    }


def test_an_unmanaged_row_creates_no_managed_directory(client) -> None:
    add(client, "work", HAND_WRITTEN)
    client.post(f"{ACCOUNTS_URL}/work/login")
    assert not Path(managed_dir_for("work")).exists()




def test_a_second_login_while_one_is_live_is_a_409(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    first = client.post(f"{ACCOUNTS_URL}/claude1/login").json()
    second = client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "login_in_progress"
    assert detail["session_id"] == first["session_id"]
    assert detail["tmux_session"] == first["tmux_session"]


def test_the_refused_second_login_spawned_nothing(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert len(client.manager.calls) == 1


def test_a_dead_login_pane_does_not_block_a_new_one(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    first = client.post(f"{ACCOUNTS_URL}/claude1/login").json()
    client.manager._registry.backends[first["session_id"]]._alive = False
    assert client.post(f"{ACCOUNTS_URL}/claude1/login").status_code == 200


def test_another_accounts_live_login_does_not_block_this_one(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    add(client, "codex1", MANAGED_CODEX)
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert client.post(f"{ACCOUNTS_URL}/codex1/login").status_code == 200


def test_a_renamed_login_pane_still_blocks_a_second_login(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    first = client.post(f"{ACCOUNTS_URL}/claude1/login").json()
    session = client.manager._registry.sessions[first["session_id"]]
    session.tmux_session = "cloude_renamed_by_the_user"

    second = client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "login_in_progress"
    assert detail["session_id"] == first["session_id"]
    assert detail["tmux_session"] == "cloude_renamed_by_the_user"


def test_a_renamed_login_pane_spawned_nothing_the_second_time(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    first = client.post(f"{ACCOUNTS_URL}/claude1/login").json()
    client.manager._registry.sessions[first["session_id"]].tmux_session = "cloude_x"
    client.post(f"{ACCOUNTS_URL}/claude1/login")
    assert len(client.manager.calls) == 1


def test_a_stranger_holding_the_expected_name_does_not_block(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    client.manager._registry.sessions["ses_stranger"] = SimpleNamespace(
        id="ses_stranger", tmux_session="cloude_login_claude1", working_dir="/"
    )
    client.manager._registry.backends["ses_stranger"] = FakeBackend()
    assert client.post(f"{ACCOUNTS_URL}/claude1/login").status_code == 200


def test_a_login_session_that_is_gone_does_not_block(client) -> None:
    add(client, "claude1", MANAGED_CLAUDE)
    first = client.post(f"{ACCOUNTS_URL}/claude1/login").json()
    client.manager._registry.sessions.pop(first["session_id"])
    client.manager._registry.backends.pop(first["session_id"])
    assert client.post(f"{ACCOUNTS_URL}/claude1/login").status_code == 200




def _codex_login_as(client, *, peer: str, host: str, via_peer: bool = False) -> dict:
    app = client.app

    class Tag:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if via_peer and scope["type"] == "http":
                scope["via_peer_link"] = True
            await self.inner(scope, receive, send)

    port = settings.port
    with TestClient(
        Tag(app), base_url=f"http://{host}:{port}", client=(peer, 50000)
    ) as caller:
        answer = caller.post(f"{ACCOUNTS_URL}/codex1/login")
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_codex_login_uses_device_auth_unless_the_browser_is_on_this_computer(
    client,
) -> None:
    from src.core.provider_ledger.login_command import login_command_for
    from src.config.provider_accounts import ProviderAccount

    add(client, "codex1", MANAGED_CODEX)
    local = _codex_login_as(client, peer="127.0.0.1", host="127.0.0.1")
    client.manager._sidecars.login_sessions.clear()
    lan = _codex_login_as(client, peer="198.51.100.18", host="198.51.100.10")
    client.manager._sidecars.login_sessions.clear()
    forwarded = _codex_login_as(
        client, peer="127.0.0.1", host="127.0.0.1", via_peer=True
    )

    assert local["device_auth"] is False
    assert lan["device_auth"] is True
    assert forwarded["device_auth"] is True
    device = client.manager._sidecars.device
    assert [device[sid] for sid in client.manager._sidecars.pending] == [
        False, True, True,
    ]

    row = ProviderAccount(id="codex1", name="c", provider="codex", managed=True)
    assert login_command_for(row, "/p").endswith(" codex login")
    assert login_command_for(row, "/p", True).endswith(" codex login --device-auth")
