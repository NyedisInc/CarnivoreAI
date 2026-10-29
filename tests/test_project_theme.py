from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pt_logs_"))
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
from src.core.composition import build_services
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus




class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path):
        self._pin_path = pin_path
        self._log_dir = log_dir

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


def _bare_manager(monkeypatch, tmp_path: Path) -> SessionManager:
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json",
        log_dir=tmp_path / "logs",
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()




def test_set_and_get_cc_theme_roundtrip(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "metal")

    dotfile = project / ".cc.theme"
    assert dotfile.is_file()
    assert dotfile.read_text(encoding="utf-8") == "metal\n"
    assert mgr._theme_store.get_project_theme(project) == "metal"


def test_set_project_theme_creates_mode_0644(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "metal")

    dotfile = project / ".cc.theme"
    mode = dotfile.stat().st_mode & 0o777
    assert mode == 0o644, f"expected 0o644, got 0o{mode:o}"




def test_get_cc_theme_returns_none_when_missing(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "fresh"
    project.mkdir()

    assert mgr._theme_store.get_project_theme(project) is None


def test_get_cc_theme_strips_whitespace(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "wsproj"
    project.mkdir()
    (project / ".cc.theme").write_text("  hermes\n\n", encoding="utf-8")

    assert mgr._theme_store.get_project_theme(project) == "hermes"


def test_get_cc_theme_returns_none_when_empty(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "emptyproj"
    project.mkdir()
    (project / ".cc.theme").write_text("\n", encoding="utf-8")

    assert mgr._theme_store.get_project_theme(project) is None




def test_resolve_project_theme_reads_the_pin_when_there_is_no_dotfile(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "pinned_only"
    project.mkdir()
    mgr._theme_store.pinned_themes["cloude_pinned_only"] = "lovecraft"

    assert mgr._theme_store.get_project_theme(project) is None
    assert mgr._theme_store.resolve_project_theme(project, "cloude_pinned_only") == (
        "lovecraft"
    )


def test_resolve_project_theme_pin_beats_dotfile(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "both"
    project.mkdir()
    mgr._theme_store.set_project_theme(project, "metal")
    mgr._theme_store.pinned_themes["cloude_both"] = "lovecraft"

    assert mgr._theme_store.resolve_project_theme(project, "cloude_both") == "lovecraft"




def test_set_cc_theme_is_atomic(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "atomic"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "metal")

    dotfile = project / ".cc.theme"
    assert dotfile.is_file()
    assert dotfile.read_text(encoding="utf-8") == "metal\n"
    assert not (project / ".cc.theme.tmp").exists()


def test_set_cc_theme_overwrites_existing(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "overwrite"
    project.mkdir()

    mgr._theme_store.set_project_theme(project, "metal")
    mgr._theme_store.set_project_theme(project, "hermes")

    assert mgr._theme_store.get_project_theme(project) == "hermes"
    assert (project / ".cc.theme").read_text(encoding="utf-8") == "hermes\n"


def test_set_cc_theme_clears_dotfile(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "clearme"
    project.mkdir()
    mgr._theme_store.set_project_theme(project, "metal")
    assert (project / ".cc.theme").exists()

    mgr._theme_store.set_project_theme(project, None)

    assert not (project / ".cc.theme").exists()
    assert mgr._theme_store.get_project_theme(project) is None


def test_set_cc_theme_raises_for_missing_working_dir(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    bogus = tmp_path / "gone"

    with pytest.raises(FileNotFoundError):
        mgr._theme_store.set_project_theme(bogus, "metal")




def test_two_sessions_same_cwd_share_the_project_default(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    project = tmp_path / "shared"
    project.mkdir()

    sess_a = Session(
        id="ses_a",
        pty_pid=None,
        working_dir=str(project),
        status=SessionStatus.RUNNING,
        tmux_session="cloude_shared_a",
    )
    sess_b = Session(
        id="ses_b",
        pty_pid=None,
        working_dir=str(project),
        status=SessionStatus.RUNNING,
        tmux_session="cloude_shared_b",
    )

    mgr._theme_store.set_project_theme(sess_a.working_dir, "metal")

    assert mgr._theme_store.get_project_theme(sess_b.working_dir) == "metal"
    assert mgr._theme_store.resolve_project_theme(
        sess_a.working_dir, sess_a.tmux_session
    ) == "metal"
    assert mgr._theme_store.resolve_project_theme(
        sess_b.working_dir, sess_b.tmux_session
    ) == "metal"




def mgr_resolve(sm, working_dir, tmux_name):
    return sm._theme_store.resolve_project_theme(working_dir, tmux_name)



def _build_route_app(monkeypatch, tmp_path):
    project = tmp_path / "routeproj"
    project.mkdir()

    sess = Session(
        id="ses_route1",
        pty_pid=None,
        working_dir=str(project),
        status=SessionStatus.RUNNING,
        tmux_session="cloude_routeproj",
    )

    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json",
        log_dir=tmp_path / "logs",
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    sm = SessionManager()
    sm._registry.sessions[sess.id] = sess

    backend = MagicMock()
    backend.tmux_session = "cloude_routeproj"
    backend.__class__.__name__ = "TmuxBackend"
    backend.is_alive = lambda: True
    sm._registry.backends[sess.id] = backend
    sm._owned.names.add("cloude_routeproj")

    monkeypatch.setattr(
        sm, "list_attachable_sessions",
        lambda: [{"name": "cloude_routeproj"}],
    )

    from src.models import SessionInfo, SessionStats

    async def fake_get_info(session_id=None):
        return SessionInfo(
            session=sess,
            recent_logs=[],
            local_servers=[],
            stats=SessionStats(),
            session_backend="tmux",
            tmux_session="cloude_routeproj",
            agent_type=None,
            pinned_theme=sess.pinned_theme,
        )

    monkeypatch.setattr(sm, "get_session_info", fake_get_info)

    app = FastAPI()
    app.state.session_manager = sm
    app.state.services = build_services(session_manager=sm)
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return app, sm, project, sess


def test_patch_theme_records_the_pin(monkeypatch, tmp_path):
    app, sm, project, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/sessions/cloude_routeproj/theme",
        json={"theme_id": "metal"},
    )
    assert resp.status_code == 200, resp.text
    assert sm._theme_store.pinned_themes["cloude_routeproj"] == "metal"


def test_patch_theme_does_not_touch_the_folder_default(monkeypatch, tmp_path):
    app, sm, project, _ = _build_route_app(monkeypatch, tmp_path)
    sm._theme_store.set_project_theme(project, "hermes")

    client = TestClient(app)
    resp = client.patch(
        "/api/v1/sessions/cloude_routeproj/theme",
        json={"theme_id": "metal"},
    )
    assert resp.status_code == 200, resp.text

    assert sm._theme_store.pinned_themes["cloude_routeproj"] == "metal"
    assert (project / ".cc.theme").read_text(encoding="utf-8") == "hermes\n"


def test_patch_theme_clears_with_null(monkeypatch, tmp_path):
    app, sm, project, _ = _build_route_app(monkeypatch, tmp_path)
    sm._theme_store.set_project_theme(project, "hermes")
    sm._theme_store.pinned_themes["cloude_routeproj"] = "metal"

    client = TestClient(app)
    resp = client.patch(
        "/api/v1/sessions/cloude_routeproj/theme",
        json={"theme_id": None},
    )
    assert resp.status_code == 200, resp.text

    assert "cloude_routeproj" not in sm._theme_store.pinned_themes
    assert (project / ".cc.theme").read_text(encoding="utf-8") == "hermes\n"
    assert mgr_resolve(sm, project, "cloude_routeproj") == "hermes"


def test_patch_theme_404_for_unknown_session(monkeypatch, tmp_path):
    app, sm, project, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/sessions/totally_bogus/theme",
        json={"theme_id": "metal"},
    )
    assert resp.status_code == 404
    assert "totally_bogus" not in sm._theme_store.pinned_themes
    assert not (project / ".cc.theme").exists()




def test_patch_deprecated_pinned_theme_alias_still_works(monkeypatch, tmp_path):
    app, sm, project, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.patch(
        "/api/v1/sessions/cloude_routeproj/pinned-theme",
        json={"pinned_theme": "hermes"},
    )
    assert resp.status_code == 200, resp.text

    assert sm._theme_store.pinned_themes["cloude_routeproj"] == "hermes"
    assert not (project / ".cc.theme").exists()


def test_patch_deprecated_alias_marked_deprecated_in_openapi(
    monkeypatch, tmp_path
):
    app, sm, project, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    spec = client.get("/openapi.json").json()
    path = spec["paths"]["/api/v1/sessions/{session_name}/pinned-theme"]
    assert path["patch"].get("deprecated") is True
    new = spec["paths"]["/api/v1/sessions/{session_name}/theme"]
    assert new["patch"].get("deprecated") is not True
