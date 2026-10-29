
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import Settings
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core.session_manager import SessionManager
from src.core.sessions.registry import SessionRegistry
from src.core.sessions.sidecars import AttachmentSidecars

MANAGED = ProviderAccount(
    id="claude1", name="Claude 1", provider="claude", managed=True
)


class FakeBackend:

    def __init__(self, fail_times: int = 0) -> None:
        self.writes: list = []
        self.fail_times = fail_times

    async def write(self, data: bytes) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("tmux send-keys -l failed: can't find window: 0")
        self.writes.append(data)


def manager_with(monkeypatch, accounts, backend, pending="claude1"):
    sm = SessionManager.__new__(SessionManager)
    sm._sidecars = AttachmentSidecars()
    if pending is not None:
        sm._sidecars.pending_logins = {"s1": pending}
    sm._registry = SessionRegistry(log_cap=lambda: 1000)
    sm._registry.backends["s1"] = backend
    monkeypatch.setattr(
        Settings,
        "load_auth_config",
        lambda self: SimpleNamespace(
            provider_accounts=SimpleNamespace(accounts=accounts)
        ),
        raising=False,
    )
    return sm


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_it_types_the_login_line_and_says_issued(monkeypatch) -> None:
    backend = FakeBackend()
    sm = manager_with(monkeypatch, [MANAGED], backend)

    assert asyncio.run(sm.flush_pending_login("s1")) == "issued"
    assert backend.writes == [
        (
            f"CLAUDE_CONFIG_DIR={managed_dir_for('claude1')} "
            "command claude auth login\n"
        ).encode()
    ]


def test_the_pending_login_is_popped_so_a_reconnect_never_retypes_it(
    monkeypatch,
) -> None:
    backend = FakeBackend()
    sm = manager_with(monkeypatch, [MANAGED], backend)

    asyncio.run(sm.flush_pending_login("s1"))
    assert sm._sidecars.pending_logins == {}
    assert asyncio.run(sm.flush_pending_login("s1")) == "none"
    assert len(backend.writes) == 1


def test_a_pane_with_nothing_pending_answers_none(monkeypatch) -> None:
    backend = FakeBackend()
    sm = manager_with(monkeypatch, [MANAGED], backend, pending=None)

    assert asyncio.run(sm.flush_pending_login("s1")) == "none"
    assert backend.writes == []


def test_an_account_removed_since_the_spawn_answers_none(monkeypatch) -> None:
    backend = FakeBackend()
    sm = manager_with(monkeypatch, [], backend)

    assert asyncio.run(sm.flush_pending_login("s1")) == "none"
    assert backend.writes == []


def test_a_session_with_no_backend_answers_none(monkeypatch) -> None:
    backend = FakeBackend()
    sm = manager_with(monkeypatch, [MANAGED], backend)
    sm._registry.backends.clear()

    assert asyncio.run(sm.flush_pending_login("s1")) == "none"


def test_a_pane_that_refuses_every_write_answers_failed(monkeypatch) -> None:
    backend = FakeBackend(fail_times=99)
    sm = manager_with(monkeypatch, [MANAGED], backend)
    monkeypatch.setattr(
        "src.core.session_manager._TERMINAL_COMMAND_WRITE_DELAY_SECONDS", 0
    )

    assert asyncio.run(sm.flush_pending_login("s1")) == "failed"
    assert backend.writes == []


def test_a_failed_login_is_still_popped(monkeypatch) -> None:
    backend = FakeBackend(fail_times=99)
    sm = manager_with(monkeypatch, [MANAGED], backend)
    monkeypatch.setattr(
        "src.core.session_manager._TERMINAL_COMMAND_WRITE_DELAY_SECONDS", 0
    )

    asyncio.run(sm.flush_pending_login("s1"))
    assert sm._sidecars.pending_logins == {}


def test_an_unmanaged_row_types_its_own_pointer_made_absolute(monkeypatch) -> None:
    account = ProviderAccount(
        id="claude1",
        name="Work",
        provider="claude",
        claude_config_dir="~/.claude-work",
    )
    backend = FakeBackend()
    sm = manager_with(monkeypatch, [account], backend)

    asyncio.run(sm.flush_pending_login("s1"))
    expanded = os.path.realpath(os.path.expanduser("~/.claude-work"))
    assert backend.writes == [
        f"CLAUDE_CONFIG_DIR={expanded} command claude auth login\n".encode()
    ]


def test_the_sidecar_holds_an_id_and_never_a_command_string(monkeypatch) -> None:
    sidecars = AttachmentSidecars()
    sidecars.set_pending_login("s1", "claude1")
    assert sidecars.pending_logins == {"s1": "claude1"}
    assert sidecars.take_pending_login("s1") == "claude1"
    assert sidecars.take_pending_login("s1") is None
