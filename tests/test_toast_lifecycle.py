from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest


os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
from src.core import toast_auto_ack
from src.core.composition import build_services

from src.api.auth import require_auth
from src.core.session_manager import SessionManager
from src.core.sessions.theme_accents import ThemeAccents
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


def _register_session(mgr: SessionManager, sid: str, working_dir: Path) -> Session:
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(working_dir),
        status=SessionStatus.RUNNING,
        tmux_session=None,
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.subscribers.setdefault(sid, [])
    return sess


_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")




def test_record_toast_returns_uuid_and_stores(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "proj"
    work.mkdir()
    _register_session(mgr, "ses_record", work)

    toast = mgr.record_toast(
        session_id="ses_record",
        kind="Notification",
        title="hello",
        body="world",
    )

    assert _UUID_HEX_RE.match(toast.id), f"id not uuid4-hex: {toast.id!r}"
    assert toast.session_id == "ses_record"
    assert toast.kind == "Notification"
    assert toast.title == "hello"
    assert toast.body == "world"
    assert toast.acknowledged is False
    assert toast.color is None or isinstance(toast.color, str)

    stored = mgr._toast_inbox.get("ses_record")
    assert len(stored) == 1
    assert stored[0].id == toast.id


def test_record_toast_unknown_session_raises(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        mgr.record_toast(
            session_id="does_not_exist",
            kind="Notification",
            title="ghost",
        )




def test_record_toast_prepends_newest_first(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "p"
    work.mkdir()
    _register_session(mgr, "ses_order", work)

    t1 = mgr.record_toast("ses_order", "Notification", "first")
    t2 = mgr.record_toast("ses_order", "Notification", "second")
    t3 = mgr.record_toast("ses_order", "Notification", "third")

    stored = mgr._toast_inbox.get("ses_order")
    assert [t.id for t in stored] == [t3.id, t2.id, t1.id]




def test_record_toast_prunes_to_50_acked(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "prune"
    work.mkdir()
    _register_session(mgr, "ses_prune", work)

    toasts = []
    for i in range(100):
        toasts.append(
            mgr.record_toast("ses_prune", "Notification", f"t{i}")
        )

    for t in toasts[:60]:
        mgr._toast_inbox.ack("ses_prune", t.id, toast_auto_ack.ACK_REASON_DISMISSED)

    stored = mgr._toast_inbox.get("ses_prune")
    acked = [t for t in stored if t.acknowledged]
    unacked = [t for t in stored if not t.acknowledged]

    assert len(unacked) == 40
    assert len(acked) == 50




def test_ack_toast_returns_true_when_found(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "ack"
    work.mkdir()
    _register_session(mgr, "ses_ack", work)

    t = mgr.record_toast("ses_ack", "Stop", "go")

    assert mgr._toast_inbox.ack("ses_ack", t.id, toast_auto_ack.ACK_REASON_DISMISSED) is True
    assert mgr._toast_inbox.ack("ses_ack", t.id, toast_auto_ack.ACK_REASON_DISMISSED) is False
    stored = mgr._toast_inbox.get("ses_ack")
    assert stored[0].acknowledged is True


def test_ack_toast_returns_false_when_not_found(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "miss"
    work.mkdir()
    _register_session(mgr, "ses_miss", work)

    assert mgr._toast_inbox.ack("ses_miss", "nonexistent_id", toast_auto_ack.ACK_REASON_DISMISSED) is False
    assert mgr._toast_inbox.ack("nope", "whatever", toast_auto_ack.ACK_REASON_DISMISSED) is False




def test_wipe_session_state_clears_pending_toasts(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "wipe"
    work.mkdir()
    _register_session(mgr, "ses_wipe", work)
    mgr.record_toast("ses_wipe", "Notification", "doomed")
    assert len(mgr._toast_inbox.get("ses_wipe")) == 1

    mgr._wipe_session_state("ses_wipe")

    assert mgr._toast_inbox.get("ses_wipe") == []
    assert "ses_wipe" not in mgr._toast_inbox.pending




def test_get_unacked_toasts_filters_correctly(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "filter"
    work.mkdir()
    _register_session(mgr, "ses_filter", work)

    t1 = mgr.record_toast("ses_filter", "Notification", "a")
    t2 = mgr.record_toast("ses_filter", "Notification", "b")
    t3 = mgr.record_toast("ses_filter", "Notification", "c")
    mgr._toast_inbox.ack("ses_filter", t2.id, toast_auto_ack.ACK_REASON_DISMISSED)

    all_toasts = mgr._toast_inbox.get("ses_filter")
    unacked = mgr._toast_inbox.get("ses_filter", unacked_only=True)

    assert len(all_toasts) == 3
    assert len(unacked) == 2
    assert {t.id for t in unacked} == {t1.id, t3.id}




def test_session_accent_color_resolution(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "themed"
    work.mkdir()
    mgr._theme_store.set_project_theme(work, "matrix")
    _register_session(mgr, "ses_themed", work)

    toast = mgr.record_toast("ses_themed", "Notification", "neo")

    assert toast.color == "#00ff41", f"unexpected color: {toast.color!r}"


def test_session_accent_color_none_when_no_theme(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "nothemed"
    work.mkdir()
    _register_session(mgr, "ses_nothemed", work)

    toast = mgr.record_toast("ses_nothemed", "Notification", "blank")

    assert toast.color is None


def test_session_accent_color_memoization(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    work = tmp_path / "memo"
    work.mkdir()
    mgr._theme_store.set_project_theme(work, "matrix")
    _register_session(mgr, "ses_memo", work)

    mgr.record_toast("ses_memo", "Notification", "first")
    assert "matrix" in mgr._theme_store.accent_cache
    assert mgr._theme_store.accent_cache["matrix"] == "#00ff41"

    monkeypatch.setattr(
        ThemeAccents,
        "themes_dir",
        staticmethod(lambda: tmp_path / "does_not_exist"),
    )
    t2 = mgr.record_toast("ses_memo", "Notification", "second")
    assert t2.color == "#00ff41"




def _build_route_app(monkeypatch, tmp_path):
    project = tmp_path / "routeproj"
    project.mkdir()
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses_route", project)

    app = FastAPI()
    app.state.session_manager = mgr
    app.state.services = build_services(session_manager=mgr)
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True

    return app, mgr


def test_post_toast_endpoint_creates_and_returns_toast(monkeypatch, tmp_path):
    app, mgr = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/sessions/ses_route/toasts",
        json={"kind": "PermissionRequest", "title": "approve?", "body": "/etc"},
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["session_id"] == "ses_route"
    assert payload["kind"] == "PermissionRequest"
    assert payload["title"] == "approve?"
    assert payload["body"] == "/etc"
    assert _UUID_HEX_RE.match(payload["id"])
    stored = mgr._toast_inbox.get("ses_route")
    assert len(stored) == 1
    assert stored[0].id == payload["id"]


def test_post_toast_endpoint_404_for_unknown_session(monkeypatch, tmp_path):
    app, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/sessions/ses_ghost/toasts",
        json={"kind": "Notification", "title": "x"},
    )
    assert resp.status_code == 404


def test_get_toasts_endpoint_lists_and_filters(monkeypatch, tmp_path):
    app, mgr = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    t1 = mgr.record_toast("ses_route", "Notification", "alpha")
    t2 = mgr.record_toast("ses_route", "Notification", "beta")
    mgr._toast_inbox.ack("ses_route", t1.id, toast_auto_ack.ACK_REASON_DISMISSED)

    resp_all = client.get("/api/v1/sessions/ses_route/toasts")
    assert resp_all.status_code == 200
    assert len(resp_all.json()) == 2

    resp_un = client.get("/api/v1/sessions/ses_route/toasts?unacked=true")
    assert resp_un.status_code == 200
    payload = resp_un.json()
    assert len(payload) == 1
    assert payload[0]["id"] == t2.id


def test_post_ack_endpoint_marks_acked(monkeypatch, tmp_path):
    app, mgr = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    t = mgr.record_toast("ses_route", "Notification", "ack me")
    resp = client.post(
        f"/api/v1/toasts/{t.id}/ack",
        params={"session_id": "ses_route"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    stored = mgr._toast_inbox.get("ses_route")
    assert stored[0].acknowledged is True


def test_post_ack_endpoint_idempotent_on_double_call(monkeypatch, tmp_path):
    app, mgr = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    t = mgr.record_toast("ses_route", "Notification", "twice")
    client.post(f"/api/v1/toasts/{t.id}/ack", params={"session_id": "ses_route"})
    resp2 = client.post(
        f"/api/v1/toasts/{t.id}/ack", params={"session_id": "ses_route"}
    )

    assert resp2.status_code == 200
    assert resp2.json().get("success") is True
    stored = mgr._toast_inbox.get("ses_route")
    assert stored[0].acknowledged is True


def test_post_ack_endpoint_unknown_toast_returns_noop(monkeypatch, tmp_path):
    app, _ = _build_route_app(monkeypatch, tmp_path)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/toasts/ghost_id/ack",
        params={"session_id": "ses_route"},
    )
    assert resp.status_code == 200
    assert resp.json().get("success") is True
