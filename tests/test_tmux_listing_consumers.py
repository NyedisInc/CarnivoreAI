
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tlc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tlc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.core.tmux_listing import (
    REASON_NO_SERVER,
    REASON_PROBE_ERROR,
    REASON_TIMEOUT,
    REASON_TMUX_MISSING,
    TmuxListing,
)




class _StubSettings:

    def __init__(self, root: Path, port: int = 5001):
        self._root = root
        self.port = port

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    def get_session_metadata_path(self) -> Path:
        return self._root / "session_metadata.json"

    def get_log_directory(self) -> Path:
        return self._root / "logs"

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    @property
    def default_working_dir(self) -> str:
        return str(self._root)

    @property
    def log_buffer_size(self) -> int:
        return 100


class _ProbeBackend:

    def __init__(self, listing: TmuxListing):
        self._listing = listing
        self.tmux_session = None

    def discover_existing(self) -> TmuxListing:
        return self._listing

    def list_pane_status_all(self) -> TmuxListing:
        return TmuxListing.answered([])


def _manager(monkeypatch, tmp_path: Path) -> SessionManager:
    stub = _StubSettings(tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


@pytest.mark.parametrize(
    "listing",
    [
        TmuxListing.unavailable(REASON_TMUX_MISSING, detail="tmux not found on PATH"),
        TmuxListing.unavailable(REASON_TIMEOUT),
        TmuxListing.unavailable("exit_1", detail="lost server"),
        TmuxListing.unavailable(REASON_PROBE_ERROR),
    ],
    ids=["tmux_missing", "timeout", "exit_1", "probe_error"],
)
@pytest.mark.asyncio
async def test_failed_probe_does_not_prune_owned_sessions(monkeypatch, tmp_path, listing):
    mgr = _manager(monkeypatch, tmp_path)
    owned = {"cloude_Test", "cloude_asd", "cloude_fs2", "cloude_ses_ec5bf2a3"}
    mgr._owned.names = set(owned)
    mgr._theme_store.pinned_themes = {"cloude_Test": "matrix"}

    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend(listing),
    )
    await mgr._lifespan_tmux_reconcile()

    assert mgr._owned.names == owned, (
        "a probe that could not evaluate pruned ownership records; an "
        "unanswered question was treated as an answer of zero"
    )
    assert mgr._theme_store.pinned_themes == {"cloude_Test": "matrix"}, (
        "a session's pinned theme was dropped by the reconcile"
    )


@pytest.mark.asyncio
async def test_successful_empty_probe_still_prunes(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    mgr._owned.names = {"cloude_gone"}
    mgr._theme_store.pinned_themes = {"cloude_gone": "matrix"}

    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend(
            TmuxListing.answered([], reason=REASON_NO_SERVER)
        ),
    )
    await mgr._lifespan_tmux_reconcile()

    assert mgr._owned.names == set(), (
        "tmux answered 'no server running', which is a real zero - the "
        "stale ownership record should have been pruned"
    )
    assert mgr._theme_store.pinned_themes == {"cloude_gone": "matrix"}, (
        "the pin was pruned because its session was not running; that is "
        "the user's theme choice, and it must outlive the tmux session"
    )


@pytest.mark.asyncio
async def test_live_sessions_survive_a_failed_probe_and_prune_when_gone(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    mgr._owned.names = {"cloude_alive", "cloude_gone"}

    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend(TmuxListing.answered(["cloude_alive"])),
    )
    await mgr._lifespan_tmux_reconcile()
    assert mgr._owned.names == {"cloude_alive"}




class _RouteManager:

    def __init__(self, listing: TmuxListing):
        self._listing = listing
        self.backends: dict = {}

    def list_attachable_sessions(self) -> TmuxListing:
        return self._listing

    def active_tmux_names(self) -> set:
        return set()


def _attachable_client(listing: TmuxListing):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router as sessions_router

    app = FastAPI()
    app.include_router(sessions_router, prefix="/api/v1")
    app.state.session_manager = _RouteManager(listing)
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def test_attachable_route_returns_503_when_the_listing_is_unavailable():
    client = _attachable_client(
        TmuxListing.unavailable(REASON_TIMEOUT, detail="tmux did not answer within 5.0s")
    )
    resp = client.get("/api/v1/sessions/attachable")
    assert resp.status_code == 503, (
        f"a probe that could not evaluate answered {resp.status_code} "
        f"with body {resp.text!r} - an empty list is an ANSWER"
    )
    detail = resp.json()["detail"]
    assert detail["listing_ok"] is False
    assert detail["listing_reason"] == REASON_TIMEOUT
    assert detail["listing_detail"] == "tmux did not answer within 5.0s"


def test_attachable_route_returns_200_empty_for_a_measured_zero():
    client = _attachable_client(
        TmuxListing.answered([], reason=REASON_NO_SERVER)
    )
    resp = client.get("/api/v1/sessions/attachable")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_attachable_route_rows_carry_their_listing_provenance():
    client = _attachable_client(TmuxListing.answered([
        {
            "name": "cloude_alpha",
            "created_by_cloude": True,
            "created_at_epoch": 1700000000,
            "window_count": 1,
        },
    ]))
    resp = client.get("/api/v1/sessions/attachable")
    assert resp.status_code == 200, resp.text
    row = resp.json()[0]
    assert row["listing_ok"] is True
    assert row["listing_reason"] is None
