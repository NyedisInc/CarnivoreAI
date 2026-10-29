from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tcs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tcs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
import src.api.toast_routes as toast_routes_mod
from src.core import toast_auto_ack
from src.core.composition import build_services

from src.api.auth import require_auth
from src.core import toast_history
from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus, Toast
from src.models.utc_time import utc_now


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


def _manager(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    stub = _StubSettings(tmp_path / "pinned_themes.json", tmp_path / "logs")
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


def _session(mgr: SessionManager, sid: str, work: Path) -> Session:
    work.mkdir(exist_ok=True, parents=True)
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=f"cloude_{sid}",
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.subscribers.setdefault(sid, [])
    return sess


def _app(monkeypatch, tmp_path: Path):
    mgr = _manager(monkeypatch, tmp_path)
    app = FastAPI()
    app.state.session_manager = mgr
    app.state.services = build_services(session_manager=mgr)
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.include_router(toast_routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app), mgr




def test_global_list_returns_every_sessions_toasts(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    _session(mgr, "ses_b", tmp_path / "b")
    a = mgr.record_toast("ses_a", "Notification", "from a")
    b = mgr.record_toast("ses_b", "PermissionRequest", "from b")

    resp = client.get("/api/v1/toasts")
    assert resp.status_code == 200, resp.text
    ids = {t["id"] for t in resp.json()["toasts"]}
    assert {a.id, b.id} <= ids, "the global list must carry BOTH sessions"

    per_session = client.get("/api/v1/sessions/ses_a/toasts").json()
    per_ids = {t["id"] for t in per_session}
    assert a.id in per_ids
    assert b.id not in per_ids, (
        "the per-session route must STILL be scoped - it is what makes a "
        "dismissal per session"
    )


def test_global_list_defaults_to_unacked_and_can_include_acked(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    open_toast = mgr.record_toast("ses_a", "PermissionRequest", "still open")
    done = mgr.record_toast("ses_a", "Notification", "already handled")
    assert mgr._toast_inbox.ack("ses_a", done.id, toast_auto_ack.ACK_REASON_DISMISSED) is True

    default_ids = {t["id"] for t in client.get("/api/v1/toasts").json()["toasts"]}
    assert open_toast.id in default_ids
    assert done.id not in default_ids

    all_ids = {
        t["id"] for t in client.get("/api/v1/toasts?unacked=false").json()["toasts"]
    }
    assert {open_toast.id, done.id} <= all_ids


def test_global_list_is_empty_not_an_error_with_no_sessions(monkeypatch, tmp_path):
    client, _ = _app(monkeypatch, tmp_path)
    resp = client.get("/api/v1/toasts")
    assert resp.status_code == 200
    assert resp.json() == {"toasts": [], "total": 0, "unacked_only": True}




def test_ack_is_scoped_to_the_toasts_own_session(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    _session(mgr, "ses_b", tmp_path / "b")
    b = mgr.record_toast("ses_b", "PermissionRequest", "approve?")

    wrong = client.post(f"/api/v1/toasts/{b.id}/ack?session_id=ses_a")
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["message"] == "No-op"
    assert mgr._toast_inbox.get("ses_b")[0].acknowledged is False, (
        "a toast id that is not in the named session's bucket must not be "
        "acked from it"
    )
    assert b.id in {x["id"] for x in client.get("/api/v1/toasts").json()["toasts"]}

    right = client.post(f"/api/v1/toasts/{b.id}/ack?session_id=ses_b")
    assert right.status_code == 200, right.text
    assert mgr._toast_inbox.get("ses_b")[0].acknowledged is True


def test_ack_is_idempotent_and_survives_the_same_click_twice(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    t = mgr.record_toast("ses_a", "Stop", "Your turn")

    first = client.post(f"/api/v1/toasts/{t.id}/ack?session_id=ses_a")
    second = client.post(f"/api/v1/toasts/{t.id}/ack?session_id=ses_a")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert [x.acknowledged for x in mgr._toast_inbox.get("ses_a")] == [True]


def test_dismissed_toast_does_not_come_back_on_the_next_poll(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    t = mgr.record_toast("ses_a", "Notification", "look at me")

    before = {x["id"] for x in client.get("/api/v1/toasts").json()["toasts"]}
    assert t.id in before, "negative control: it must be there BEFORE the ack"

    client.post(f"/api/v1/toasts/{t.id}/ack?session_id=ses_a")
    after = {x["id"] for x in client.get("/api/v1/toasts").json()["toasts"]}
    assert t.id not in after


def test_duplicate_hook_event_yields_one_record_and_one_dismissal(
    monkeypatch, tmp_path
):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    first = mgr.record_toast("ses_a", "Stop", "Your turn", "tail one")
    again = mgr.record_toast("ses_a", "Stop", "Your turn", "tail two")

    assert again.id == first.id
    listed = client.get("/api/v1/toasts").json()["toasts"]
    assert len([x for x in listed if x["session_id"] == "ses_a"]) == 1

    client.post(f"/api/v1/toasts/{first.id}/ack?session_id=ses_a")
    assert client.get("/api/v1/toasts").json()["toasts"] == []


def test_acking_one_session_leaves_another_sessions_toast_alone(
    monkeypatch, tmp_path
):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    _session(mgr, "ses_b", tmp_path / "b")
    a = mgr.record_toast("ses_a", "Notification", "a needs you")
    b = mgr.record_toast("ses_b", "Notification", "b needs you")

    client.post(f"/api/v1/toasts/{a.id}/ack?session_id=ses_a")
    remaining = {x["id"] for x in client.get("/api/v1/toasts").json()["toasts"]}
    assert remaining == {b.id}




def test_history_returns_dismissed_and_open_newest_first(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    _session(mgr, "ses_b", tmp_path / "b")
    old = mgr.record_toast("ses_a", "Notification", "older")
    new = mgr.record_toast("ses_b", "PermissionRequest", "newer")
    old.created_at = utc_now() - timedelta(minutes=5)
    mgr._toast_inbox.ack("ses_a", old.id, toast_auto_ack.ACK_REASON_DISMISSED)

    body = client.get("/api/v1/toasts/history").json()
    ids = [t["id"] for t in body["toasts"]]
    assert ids == [new.id, old.id], "newest first, across sessions"
    by_id = {t["id"]: t for t in body["toasts"]}
    assert by_id[old.id]["acknowledged"] is True
    assert by_id[new.id]["acknowledged"] is False
    assert body["summary"] == {
        "total": 2,
        "open": 1,
        "dismissed": 1,
        "answered": 0,
        "by_kind": {"PermissionRequest": 1, "Notification": 1},
    }


def test_history_pages_and_reports_the_next_offset(monkeypatch, tmp_path):
    client, mgr = _app(monkeypatch, tmp_path)
    _session(mgr, "ses_a", tmp_path / "a")
    base = utc_now()
    made = []
    for i in range(5):
        t = mgr.record_toast("ses_a", "Notification", f"n{i}")
        t.created_at = base - timedelta(seconds=i)
        made.append(t)

    first = client.get("/api/v1/toasts/history?limit=2&offset=0").json()
    assert [t["title"] for t in first["toasts"]] == ["n0", "n1"]
    assert first["total"] == 5
    assert first["next_offset"] == 2

    second = client.get("/api/v1/toasts/history?limit=2&offset=2").json()
    assert [t["title"] for t in second["toasts"]] == ["n2", "n3"]
    assert second["next_offset"] == 4

    last = client.get("/api/v1/toasts/history?limit=2&offset=4").json()
    assert [t["title"] for t in last["toasts"]] == ["n4"]
    assert last["next_offset"] is None, "the last page must say it is the last"


def test_history_names_its_own_retention(monkeypatch, tmp_path):
    client, _ = _app(monkeypatch, tmp_path)
    body = client.get("/api/v1/toasts/history").json()
    assert body["storage"] == toast_routes_mod.STORAGE_IN_MEMORY
    assert body["toasts"] == []
    assert body["total"] == 0


def test_history_clamps_a_hostile_limit(monkeypatch, tmp_path):
    client, _ = _app(monkeypatch, tmp_path)
    body = client.get("/api/v1/toasts/history?limit=100000").json()
    assert body["limit"] == toast_history.MAX_HISTORY_LIMIT
    zero = client.get("/api/v1/toasts/history?limit=0").json()
    assert zero["limit"] == toast_history.DEFAULT_HISTORY_LIMIT, (
        "a missing or nonsense limit means 'use the default', never "
        "'return nothing' - the second reads as an empty history"
    )
    negative = client.get("/api/v1/toasts/history?offset=-5").json()
    assert negative["offset"] == 0




def _toast(tid: str, sid: str, at: datetime, acked: bool = False) -> Toast:
    return Toast(
        id=tid, session_id=sid, kind="Notification", title=tid,
        created_at=at, acknowledged=acked,
    )


def test_collect_orders_ties_deterministically():
    at = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    buckets = {
        "s1": [_toast("a", "s1", at)],
        "s2": [_toast("c", "s2", at), _toast("b", "s2", at)],
    }
    once = [t.id for t in toast_history.collect_toasts(buckets)]
    twice = [t.id for t in toast_history.collect_toasts(buckets)]
    assert once == twice == ["c", "b", "a"]


def test_collect_filters_acked_when_asked():
    at = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    buckets = {"s1": [_toast("a", "s1", at, acked=True), _toast("b", "s1", at)]}
    assert [t.id for t in toast_history.collect_toasts(buckets, unacked_only=True)] == ["b"]
    assert len(toast_history.collect_toasts(buckets)) == 2


def test_buckets_from_inbox_tolerates_an_unmounted_inbox_and_nothing_else():
    assert toast_history.buckets_from_inbox(None) == {}

    with pytest.raises(AttributeError):
        toast_history.buckets_from_inbox(object())


def test_page_reports_total_independently_of_the_slice():
    at = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    records = [_toast(str(i), "s", at) for i in range(7)]
    items, total, nxt = toast_history.page(records, limit=3, offset=6)
    assert len(items) == 1 and total == 7 and nxt is None
    empty, total2, nxt2 = toast_history.page(records, limit=3, offset=99)
    assert empty == [] and total2 == 7 and nxt2 is None


def test_summarize_counts_the_whole_set():
    at = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    records = [
        _toast("a", "s", at, acked=True),
        _toast("b", "s", at),
        _toast("c", "s", at),
    ]
    records[2].kind = "Stop"
    assert toast_history.summarize(records) == {
        "total": 3, "open": 2, "dismissed": 1, "answered": 0,
        "by_kind": {"Notification": 2, "Stop": 1},
    }
    assert toast_history.summarize([]) == {
        "total": 0, "open": 0, "dismissed": 0, "answered": 0, "by_kind": {},
    }
