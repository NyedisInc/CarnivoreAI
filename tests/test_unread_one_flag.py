
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_uof_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_uof_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
from src.api.auth import require_auth
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus

TMUX_NAME = "cloude_oneflag"
SESSION_ID = "ses_oneflag"
EPOCH = 1788444912


class _StubSettings:

    def __init__(self, root: Path):
        self._root = root
        self.port = 5001

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    def get_session_metadata_path(self) -> Path:
        return self._root / "logs" / "session_metadata.json"


class _FakeBackend:

    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session

    def is_alive(self) -> bool:
        return True


def _manager(monkeypatch, tmp_path: Path) -> SessionManager:
    stub = _StubSettings(tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    mgr = SessionManager()

    mgr._registry.sessions[SESSION_ID] = Session(
        id=SESSION_ID,
        pty_pid=None,
        working_dir=str(tmp_path),
        status=SessionStatus.RUNNING,
        tmux_session=TMUX_NAME,
    )
    mgr._registry.backends[SESSION_ID] = _FakeBackend(TMUX_NAME)
    mgr._registry.subscribers.setdefault(SESSION_ID, [])

    monkeypatch.setattr(
        mgr,
        "_build_tmux_status_map",
        lambda: {TMUX_NAME: {"status": "idle", "created_at_epoch": EPOCH}},
    )
    monkeypatch.setattr(
        mgr,
        "list_attachable_sessions",
        lambda: [{"name": TMUX_NAME, "created_at_epoch": EPOCH}],
    )
    assert mgr._instance_epochs == {}, "the cache must start empty or this proves nothing"
    return mgr


def _client(mgr: SessionManager) -> TestClient:
    app = FastAPI()
    app.state.session_manager = mgr
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


async def _unread_on_list(mgr: SessionManager) -> bool:
    infos = await mgr.list_session_infos()
    assert len(infos) == 1, f"expected one row, got {len(infos)}"
    return bool(infos[0].unread)




@pytest.mark.asyncio
async def test_marking_through_the_route_shows_unread_on_the_list(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    assert await _unread_on_list(mgr) is False

    resp = _client(mgr).patch(
        f"/api/v1/sessions/{TMUX_NAME}/unread", json={"unread": True}
    )
    assert resp.status_code == 200, resp.text

    assert await _unread_on_list(mgr) is True


@pytest.mark.asyncio
async def test_the_list_read_survives_an_empty_instance_epoch_cache(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    mgr.set_manual_unread(TMUX_NAME, True)

    stored = list(mgr._unread_store.raw)
    assert stored == [f"{TMUX_NAME}@{EPOCH}"], stored
    assert SESSION_ID not in mgr._instance_epochs

    assert await _unread_on_list(mgr) is True


@pytest.mark.asyncio
async def test_the_auto_writer_and_the_control_write_the_same_key(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)

    mgr._unread_store.set_flag(
        TMUX_NAME, "auto", True, epoch=mgr._unread_epoch(TMUX_NAME)
    )
    after_auto = set(mgr._unread_store.raw)

    mgr.set_manual_unread(TMUX_NAME, True)
    after_mark = set(mgr._unread_store.raw)

    assert after_auto == after_mark == {f"{TMUX_NAME}@{EPOCH}"}




@pytest.mark.asyncio
async def test_marking_twice_is_idempotent(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    client = _client(mgr)

    for _ in range(2):
        assert client.patch(
            f"/api/v1/sessions/{TMUX_NAME}/unread", json={"unread": True}
        ).status_code == 200

    assert await _unread_on_list(mgr) is True
    assert len(mgr._unread_store.raw) == 1


@pytest.mark.asyncio
async def test_unmarking_through_the_route_clears_the_list_field(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    client = _client(mgr)
    client.patch(f"/api/v1/sessions/{TMUX_NAME}/unread", json={"unread": True})
    assert await _unread_on_list(mgr) is True

    assert client.patch(
        f"/api/v1/sessions/{TMUX_NAME}/unread", json={"unread": False}
    ).status_code == 200
    assert await _unread_on_list(mgr) is False
    assert mgr._unread_store.raw == {}


@pytest.mark.asyncio
async def test_unmarking_twice_is_idempotent(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    client = _client(mgr)
    for _ in range(2):
        assert client.patch(
            f"/api/v1/sessions/{TMUX_NAME}/unread", json={"unread": False}
        ).status_code == 200
    assert await _unread_on_list(mgr) is False


@pytest.mark.asyncio
async def test_binding_a_terminal_clears_a_manually_marked_session(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    _client(mgr).patch(f"/api/v1/sessions/{TMUX_NAME}/unread", json={"unread": True})
    assert await _unread_on_list(mgr) is True

    mgr.mark_session_viewed(SESSION_ID)
    assert await _unread_on_list(mgr) is False


@pytest.mark.asyncio
async def test_binding_a_terminal_clears_an_auto_flagged_session(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    mgr._unread_store.set_flag(
        TMUX_NAME, "auto", True, epoch=mgr._unread_epoch(TMUX_NAME)
    )
    assert await _unread_on_list(mgr) is True

    mgr.mark_session_viewed(SESSION_ID)
    assert await _unread_on_list(mgr) is False




@pytest.mark.asyncio
async def test_an_unmarked_session_is_not_reported_unread(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    mgr.set_manual_unread("cloude_someone_else", True)
    assert await _unread_on_list(mgr) is False
