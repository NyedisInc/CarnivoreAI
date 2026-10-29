from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rn_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rn_logs_"))
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
from src.api.websocket import connection_manager
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus




class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path):
        self._pin_path = pin_path
        self._log_dir = log_dir

    def load_auth_config(self):
        raise FileNotFoundError("no config.json in this stub")

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


class _FakeBackend:

    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session
        self.rename_calls: list[str] = []
        self.fail_next: bool = False

    async def rename_session(self, new_name: str) -> None:
        self.rename_calls.append(new_name)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated tmux failure")
        self.tmux_session = new_name

    def is_alive(self) -> bool:
        return True


def _bare_manager(monkeypatch, tmp_path: Path) -> SessionManager:
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json",
        log_dir=tmp_path / "logs",
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


def _register(
    mgr: SessionManager,
    sid: str,
    working_dir: Path,
    tmux_session: str,
    owned: bool = True,
) -> tuple[Session, _FakeBackend]:
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(working_dir),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_session,
    )
    backend = _FakeBackend(tmux_session=tmux_session)
    mgr._registry.sessions[sid] = sess
    mgr._registry.backends[sid] = backend
    mgr._registry.subscribers.setdefault(sid, [])
    mgr._registry.last_session_id = sid
    if owned:
        mgr._owned.names.add(tmux_session)
    return sess, backend




@pytest.mark.asyncio
async def test_rename_persists_in_session_object(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    sess, backend = _register(mgr, "ses_a", work, "cloude_old", owned=True)

    info = await mgr.rename_session("ses_a", "newname")

    assert backend.rename_calls == ["newname"]
    assert sess.tmux_session == "newname"
    assert "cloude_old" not in mgr._owned.names
    assert "newname" in mgr._owned.names
    assert info.tmux_session == "newname"


@pytest.mark.asyncio
async def test_rename_repins_themes(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "themed"
    work.mkdir()
    _register(mgr, "ses_t", work, "cloude_themed", owned=True)

    mgr._theme_store.pinned_themes["cloude_themed"] = "matrix"
    mgr._theme_store.save()

    await mgr.rename_session("ses_t", "themed2")

    assert "cloude_themed" not in mgr._theme_store.pinned_themes
    assert mgr._theme_store.pinned_themes.get("themed2") == "matrix"




@pytest.mark.asyncio
async def test_rename_adopted_external_session(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "ext"
    work.mkdir()
    _register(
        mgr,
        "adopted:external_a",
        work,
        "external_a",
        owned=False,
    )

    await mgr.rename_session("adopted:external_a", "external_b")

    assert "external_a" not in mgr._owned.names
    assert "external_b" not in mgr._owned.names
    assert mgr._registry.sessions["adopted:external_a"].tmux_session == "external_b"




@pytest.mark.asyncio
async def test_rename_conflict_with_existing_session(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "a"
    work.mkdir()
    work2 = tmp_path / "b"
    work2.mkdir()
    _register(mgr, "ses_a", work, "name_a", owned=True)
    _, b_backend = _register(mgr, "ses_b", work2, "name_b", owned=True)

    with pytest.raises(FileExistsError):
        await mgr.rename_session("ses_a", "name_b")

    assert mgr._registry.sessions["ses_a"].tmux_session == "name_a"
    assert b_backend.tmux_session == "name_b"


@pytest.mark.asyncio
async def test_rename_conflict_with_owned_but_detached(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "a"
    work.mkdir()
    _register(mgr, "ses_a", work, "name_a", owned=True)
    mgr._owned.names.add("ghost_name")

    with pytest.raises(FileExistsError):
        await mgr.rename_session("ses_a", "ghost_name")




@pytest.mark.asyncio
async def test_rename_unknown_session_id_raises(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        await mgr.rename_session("does_not_exist", "newname")




@pytest.mark.asyncio
async def test_rename_noop_same_name(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "p"
    work.mkdir()
    _, backend = _register(mgr, "ses_a", work, "samename", owned=True)

    info = await mgr.rename_session("ses_a", "samename")

    assert backend.rename_calls == []
    assert info.tmux_session == "samename"
    assert "samename" in mgr._owned.names




def _build_route_app(monkeypatch, tmp_path):
    project = tmp_path / "routeproj"
    project.mkdir()
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register(mgr, "ses_route", project, "cloude_route", owned=True)

    app = FastAPI()
    app.state.session_manager = mgr
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True

    return app, mgr




def test_a_label_with_spaces_is_no_longer_rejected(monkeypatch, tmp_path):
    app, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/sessions/ses_route/name",
        json={"new_name": "Media Compression"},
    )
    assert resp.status_code != 400, (
        "a label containing a space must not be refused as malformed"
    )


@pytest.mark.parametrize(
    "label",
    ["has:colon", "has.dot", "has/slash", "has!bang", "client (v2) 50%"],
)
def test_punctuation_is_no_longer_rejected(monkeypatch, tmp_path, label):
    app, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/sessions/ses_route/name", json={"new_name": label}
    )
    assert resp.status_code != 400


@pytest.mark.parametrize(
    "label",
    ["", "   ", "line\nbreak", "tab\there", "a" * 201],
)
def test_a_label_that_cannot_be_rendered_is_still_a_400(
    monkeypatch, tmp_path, label
):
    app, mgr = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/sessions/ses_route/name", json={"new_name": label}
    )
    assert resp.status_code == 400, resp.text
    assert mgr._registry.sessions["ses_route"].tmux_session == "cloude_route"


def test_labelling_never_moves_the_tmux_name(monkeypatch, tmp_path):
    app, mgr = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    client.patch(
        "/api/v1/sessions/ses_route/name",
        json={"new_name": "Something Entirely Different"},
    )

    assert mgr._registry.sessions["ses_route"].tmux_session == "cloude_route"
    assert "cloude_route" in mgr._owned.names
    assert "Something Entirely Different" not in mgr._owned.names


def test_rename_unknown_session_id_404(monkeypatch, tmp_path):
    app, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/sessions/does_not_exist/name",
        json={"new_name": "Whatever"},
    )
    assert resp.status_code == 404
