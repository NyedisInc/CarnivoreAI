
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mute_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mute_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
import src.api.session_records_routes as records_routes_mod
from src.api.auth import require_auth
from src.core import session_store
from src.core.db_steps import run_chain
from src.core.notifications import contracts
from src.core.notifications.engine import NotifyEngine
from src.core.notifications.sources.toast import attention_notify_type
from src.core.attention.raise_gate import resolve_raise
from src.core.session_manager import SessionManager
from src.core.session_notification_policy import (
    POLICY_MUTED,
    POLICY_UNKNOWN,
    POLICY_UNMUTED,
    NotificationPolicyStore,
    hydrate_from_datastore,
)
from src.core.session_status import STATUS_RUNNING
from src.models import Session, SessionStatus

TMUX_SOCKET = "cloude"
TMUX_NAME = "cloude_mute_proj"
TMUX_EPOCH = 1_700_000_000

TRUST_PROMPT_TAIL = """
 Accessing workspace:

 /private/tmp/cc-probe/workdir

 Quick safety check: Is this a project you created or one you trust? (Like your own code, a
 well-known open source project, or work from your team). If not, take a moment to review what's in
 this folder first.

 Claude Code'll be able to read, edit, and execute files here.

 > No, exit
   Yes, I trust this folder
"""




def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    with conn:
        run_chain(conn, 0, __import__(
            "src.core.db_models", fromlist=["CURRENT_SCHEMA_VERSION"]
        ).CURRENT_SCHEMA_VERSION)
    return conn


def _insert_session(
    conn: sqlite3.Connection,
    *,
    session_uuid: str,
    tmux_name: str = TMUX_NAME,
    epoch: int = TMUX_EPOCH,
    parent_session_id=None,
) -> int:
    cur = conn.execute(
        "INSERT INTO sessions (session_uuid, origin, lifecycle, "
        "project_attribution, tmux_socket, tmux_name, tmux_created_epoch, "
        "parent_session_id, created_at, updated_at) "
        "VALUES (?, 'created', 'running', 'none', ?, ?, ?, ?, ?, ?)",
        (
            session_uuid,
            TMUX_SOCKET,
            tmux_name,
            epoch,
            parent_session_id,
            "2026-09-09T00:00:00Z",
            "2026-09-09T00:00:00Z",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path, port: int = 5001):
        self._pin_path = pin_path
        self._log_dir = log_dir
        self.port = port

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

    def __init__(self, tmux_session: str, socket_name: str = TMUX_SOCKET):
        self.tmux_session = tmux_session
        self.socket_name = socket_name

    def is_alive(self) -> bool:
        return True


class _RecordingSink:

    def __init__(self):
        self.emitted: list = []

    def __call__(self, event) -> None:
        self.emitted.append(event)


def _build_manager(monkeypatch, tmp_path, *, store=None, sink=None):
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json",
        log_dir=tmp_path / "logs",
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    mgr = SessionManager()

    work = tmp_path / "mute_proj"
    work.mkdir(exist_ok=True)
    mgr._registry.sessions["ses_mute"] = Session(
        id="ses_mute",
        pty_pid=None,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=TMUX_NAME,
    )
    mgr._registry.backends["ses_mute"] = _FakeBackend(TMUX_NAME)
    mgr._registry.subscribers.setdefault("ses_mute", [])
    mgr._instance_epochs["ses_mute"] = TMUX_EPOCH
    mgr.hook_tokens.mint("ses_mute")
    if store is not None:
        mgr.attach_notification_policy_store(store)
    if sink is not None:
        monkeypatch.setattr(contracts, "_sink", sink)

    return mgr


def _raise_attempt(mgr, kind: str):
    attached = mgr._notification_policy_store is not None
    verdict = resolve_raise(
        kind,
        policy_store_attached=attached,
        policy=mgr.notification_policy_for("ses_mute") if attached else None,
    )
    if not verdict.raises_toast:
        return verdict, None
    toast = mgr.record_toast(
        "ses_mute", kind=kind, title="t", body="b",
        notify_type=attention_notify_type(kind, None),
    )
    return verdict, toast


def _muted_store(session_uuid: str = "u1", generation: int = 1):
    store = NotificationPolicyStore()
    store.hydrate(
        [
            {
                "session_uuid": session_uuid,
                "tmux_socket": TMUX_SOCKET,
                "tmux_name": TMUX_NAME,
                "tmux_created_epoch": TMUX_EPOCH,
                "muted": True,
                "generation": generation,
            }
        ]
    )
    return store


def _unmuted_store(session_uuid: str = "u1", generation: int = 0):
    store = NotificationPolicyStore()
    store.hydrate(
        [
            {
                "session_uuid": session_uuid,
                "tmux_socket": TMUX_SOCKET,
                "tmux_name": TMUX_NAME,
                "tmux_created_epoch": TMUX_EPOCH,
                "muted": False,
                "generation": generation,
            }
        ]
    )
    return store




def test_the_mute_is_written_to_the_row_and_survives_reopening_the_file(tmp_path):
    db = tmp_path / "cloude.db"
    conn = _make_db(db)
    _insert_session(conn, session_uuid="u1")

    committed = session_store.set_notification_mute(conn, "u1", muted=True)
    assert committed["muted"] is True
    assert committed["changed"] is True
    conn.close()

    reopened = sqlite3.connect(str(db))
    reopened.row_factory = sqlite3.Row
    try:
        assert session_store.get_notification_policy(reopened, "u1") == {
            "muted": True,
            "generation": 1,
        }
    finally:
        reopened.close()


def test_the_mute_survives_a_same_record_session_restart(tmp_path):
    conn = _make_db(tmp_path / "cloude.db")
    _insert_session(conn, session_uuid="u1")
    session_store.set_notification_mute(conn, "u1", muted=True)

    conn.execute(
        "UPDATE sessions SET agent_type = 'claude-chrome' WHERE session_uuid = ?",
        ("u1",),
    )
    conn.commit()

    assert session_store.get_notification_policy(conn, "u1")["muted"] is True
    conn.close()


def test_a_pre_v26_database_cannot_report_a_mute_and_says_so(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    with conn:
        run_chain(conn, 0, 25)
    _insert_session(conn, session_uuid="u1")

    assert session_store.notification_policy_rows(conn) == []
    with pytest.raises(session_store.SessionNotFoundError):
        session_store.get_notification_policy(conn, "u1")
    with pytest.raises(session_store.SessionNotFoundError):
        session_store.set_notification_mute(conn, "u1", muted=True)
    conn.close()




def test_the_generation_steps_on_mute_and_on_unmute_alike(tmp_path):
    conn = _make_db(tmp_path / "cloude.db")
    _insert_session(conn, session_uuid="u1")

    assert session_store.set_notification_mute(conn, "u1", muted=True)[
        "generation"
    ] == 1
    assert session_store.set_notification_mute(conn, "u1", muted=False)[
        "generation"
    ] == 2
    assert session_store.set_notification_mute(conn, "u1", muted=True)[
        "generation"
    ] == 3
    conn.close()


def test_a_no_op_request_writes_nothing_and_does_not_step_the_generation(tmp_path):
    conn = _make_db(tmp_path / "cloude.db")
    _insert_session(conn, session_uuid="u1")
    session_store.set_notification_mute(conn, "u1", muted=True)

    again = session_store.set_notification_mute(conn, "u1", muted=True)
    assert again["changed"] is False
    assert again["generation"] == 1
    conn.close()




def test_an_unhydrated_store_answers_unknown_for_everything():
    store = NotificationPolicyStore()
    assert store.hydrated is False
    assert store.needs_hydration() is True
    assert store.for_uuid("u1").verdict == POLICY_UNKNOWN
    assert store.for_instance(TMUX_NAME, TMUX_EPOCH).verdict == POLICY_UNKNOWN


def test_unknown_suppresses_but_does_not_paint_as_muted():
    store = NotificationPolicyStore()
    verdict = store.for_uuid("u1")
    assert verdict.suppresses is True
    assert verdict.muted is False


def test_a_failed_hydration_leaves_the_store_unhydrated(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_bytes(b"this is not a sqlite database at all, not even close")

    store = NotificationPolicyStore()
    assert hydrate_from_datastore(store, db) is False
    assert store.hydrated is False
    assert store.for_uuid("u1").verdict == POLICY_UNKNOWN


def test_a_missing_database_file_hydrates_empty_and_is_a_measurement(tmp_path):
    store = NotificationPolicyStore()
    assert hydrate_from_datastore(store, tmp_path / "nothing-here.db") is True
    assert store.hydrated is True
    assert store.for_uuid("u1").verdict == POLICY_UNMUTED


def test_a_later_failed_read_cannot_downgrade_what_is_already_known(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a sqlite database")

    store = _muted_store()
    assert hydrate_from_datastore(store, corrupt) is False
    assert store.hydrated is True
    assert store.for_uuid("u1").verdict == POLICY_MUTED
    assert store.for_instance(TMUX_NAME, TMUX_EPOCH).verdict == POLICY_MUTED




class _Rig:

    def __init__(self, mgr):
        from tests.python.notifications.engine_fakes import FakeSender, FakeView, dest
        from src.core.notifications import routing_view

        self.sender = FakeSender()
        self.view = FakeView([dest()])

        async def secrets(dest_id):
            return {"k": "v"}

        self.engine = NotifyEngine(
            sender_lookup=lambda kind: self.sender,
            is_muted=lambda session_id: bool(mgr.notification_policy_for(session_id).suppresses),
            secrets_lookup=secrets,
        )
        routing_view.install_routing(lambda: self.view, None)

    async def deliver(self, session_id):
        await self.engine.handle(contracts.NotifyEvent(
            type_id="session.finished", kind="Stop", title="done", ts=1.0, session_id=session_id,
            instance_key=f"k-{session_id}"))
        await self.engine.join()
        return len(self.sender.calls)


@pytest.fixture()
def _routing_cleanup():
    yield
    from src.core.notifications import routing_view

    routing_view.uninstall_routing()


@pytest.mark.asyncio
async def test_the_engine_drops_a_muted_session_and_still_sends_an_unmuted_one(monkeypatch, tmp_path, _routing_cleanup):
    muted = _Rig(_build_manager(monkeypatch, tmp_path, store=_muted_store()))
    assert await muted.deliver("ses_mute") == 0
    unmuted = _Rig(_build_manager(monkeypatch, tmp_path, store=_unmuted_store()))
    assert await unmuted.deliver("ses_mute") == 1


@pytest.mark.asyncio
async def test_the_engine_refuses_when_the_policy_could_not_be_read(monkeypatch, tmp_path, _routing_cleanup):
    rig = _Rig(_build_manager(monkeypatch, tmp_path, store=NotificationPolicyStore()))
    assert await rig.deliver("ses_mute") == 0


@pytest.mark.asyncio
async def test_an_event_with_no_session_is_always_sent(monkeypatch, tmp_path, _routing_cleanup):
    rig = _Rig(_build_manager(monkeypatch, tmp_path, store=_muted_store()))
    assert await rig.deliver(None) == 1




@pytest.mark.parametrize(
    "kind", ["Stop", "Notification", "PermissionRequest"]
)
def test_a_muted_session_raises_no_web_alert_for_any_toast_kind(
    monkeypatch, tmp_path, kind
):
    mgr = _build_manager(
        monkeypatch, tmp_path, store=_muted_store(), sink=_RecordingSink()
    )
    verdict, toast = _raise_attempt(mgr, kind)

    assert verdict.raises_toast is False
    assert verdict.suppressed_by == "notifications_muted"
    assert toast is None
    assert mgr._toast_inbox.get("ses_mute") == []


@pytest.mark.parametrize(
    "kind", ["Stop", "Notification", "PermissionRequest"]
)
def test_a_muted_session_sends_no_external_push_either(
    monkeypatch, tmp_path, kind
):
    sink = _RecordingSink()
    mgr = _build_manager(
        monkeypatch, tmp_path, store=_muted_store(), sink=sink
    )
    _raise_attempt(mgr, kind)
    assert sink.emitted == []


@pytest.mark.parametrize(
    "kind", ["Stop", "Notification", "PermissionRequest"]
)
def test_an_unmuted_session_still_raises_and_still_pushes(
    monkeypatch, tmp_path, kind
):
    sink = _RecordingSink()
    mgr = _build_manager(
        monkeypatch, tmp_path, store=_unmuted_store(), sink=sink
    )
    verdict, toast = _raise_attempt(mgr, kind)

    assert verdict.raises_toast is True
    assert toast is not None
    assert len(mgr._toast_inbox.get("ses_mute")) == 1
    assert len(sink.emitted) == 1
    assert sink.emitted[0].session_id == "ses_mute"
    assert sink.emitted[0].type_id == attention_notify_type(kind, None)


def test_an_unreadable_policy_suppresses_rather_than_notifying(
    monkeypatch, tmp_path
):
    mgr = _build_manager(
        monkeypatch,
        tmp_path,
        store=NotificationPolicyStore(),
        sink=_RecordingSink(),
    )
    verdict, toast = _raise_attempt(mgr, "Stop")

    assert verdict.suppressed_by == "notifications_muted"
    assert toast is None
    assert mgr._toast_inbox.get("ses_mute") == []


def test_with_no_policy_store_attached_the_gate_does_not_run(
    monkeypatch, tmp_path
):
    mgr = _build_manager(monkeypatch, tmp_path, sink=_RecordingSink())
    verdict, toast = _raise_attempt(mgr, "Stop")

    assert verdict.raises_toast is True
    assert toast is not None




def test_a_muted_permission_is_suppressed_without_being_answered(monkeypatch, tmp_path):
    mgr = _build_manager(
        monkeypatch, tmp_path, store=_muted_store(), sink=_RecordingSink()
    )
    verdict, toast = _raise_attempt(mgr, "PermissionRequest")

    assert verdict.suppressed_by == "notifications_muted"
    assert toast is None


def test_a_muted_stop_still_flips_unread(monkeypatch, tmp_path):
    mgr = _build_manager(
        monkeypatch, tmp_path, store=_muted_store(), sink=_RecordingSink()
    )
    verdict, toast = _raise_attempt(mgr, "Stop")
    assert verdict.suppressed_by == "notifications_muted"
    assert toast is None

    mgr._unread_store.set_flag(
        TMUX_NAME, "auto", True, epoch=TMUX_EPOCH
    )
    assert mgr._is_unread(TMUX_NAME, TMUX_EPOCH) is True


def test_muting_does_not_acknowledge_a_toast_already_on_record(
    monkeypatch, tmp_path
):
    store = _unmuted_store()
    mgr = _build_manager(
        monkeypatch, tmp_path, store=store, sink=_RecordingSink()
    )
    _raise_attempt(mgr, "PermissionRequest")
    assert len(mgr._toast_inbox.get("ses_mute", unacked_only=True)) == 1

    store.apply("u1", muted=True, generation=1)

    remaining = mgr._toast_inbox.get("ses_mute", unacked_only=True)
    assert len(remaining) == 1
    assert remaining[0].acknowledged is False




def test_a_fork_of_a_muted_session_starts_unmuted(tmp_path):
    conn = _make_db(tmp_path / "cloude.db")
    parent_id = _insert_session(conn, session_uuid="parent")
    session_store.set_notification_mute(conn, "parent", muted=True)

    _insert_session(
        conn,
        session_uuid="child",
        tmux_name="cloude_mute_proj_fork",
        epoch=TMUX_EPOCH + 10,
        parent_session_id=parent_id,
    )

    assert session_store.get_notification_policy(conn, "parent")["muted"] is True
    assert session_store.get_notification_policy(conn, "child") == {
        "muted": False,
        "generation": 0,
    }
    conn.close()


def test_a_session_created_after_hydration_is_unmuted_not_unknown(tmp_path):
    store = _muted_store()
    verdict = store.for_instance("cloude_brand_new", TMUX_EPOCH + 99)
    assert verdict.verdict == POLICY_UNMUTED
    assert verdict.suppresses is False




def test_a_reused_name_does_not_inherit_the_dead_session_s_mute():
    store = _muted_store()
    successor = store.for_instance(TMUX_NAME, TMUX_EPOCH + 1)
    assert successor.verdict == POLICY_UNMUTED

    assert store.for_instance(TMUX_NAME, TMUX_EPOCH).verdict == POLICY_MUTED


def test_the_write_refuses_an_expected_instance_that_no_longer_matches(tmp_path):
    conn = _make_db(tmp_path / "cloude.db")
    _insert_session(conn, session_uuid="u1")

    with pytest.raises(session_store.SessionInstanceMismatchError):
        session_store.set_notification_mute(
            conn,
            "u1",
            muted=True,
            expected_tmux_name=TMUX_NAME,
            expected_tmux_created_epoch=TMUX_EPOCH + 1,
        )
    assert session_store.get_notification_policy(conn, "u1")["muted"] is False

    ok = session_store.set_notification_mute(
        conn,
        "u1",
        muted=True,
        expected_tmux_name=TMUX_NAME,
        expected_tmux_created_epoch=TMUX_EPOCH,
    )
    assert ok["muted"] is True
    conn.close()




def _records_app(monkeypatch, tmp_path, store=None):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)

    class _S:
        def get_state_dir(self):
            return state

    monkeypatch.setattr(records_routes_mod, "settings", _S())

    from src.core.db import db_path_for

    conn = _make_db(db_path_for(state))

    class _Mgr:
        pass

    mgr = _Mgr()
    mgr._notification_policy_store = store

    app = FastAPI()
    app.state.session_manager = mgr
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app), conn, mgr


def test_the_patch_route_commits_and_reports_the_generation(
    monkeypatch, tmp_path
):
    client, conn, _ = _records_app(monkeypatch, tmp_path)
    _insert_session(conn, session_uuid="u1")

    resp = client.patch(
        "/api/v1/sessions/records/u1/notifications", json={"muted": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"muted": True, "policy_generation": 1}

    again = client.patch(
        "/api/v1/sessions/records/u1/notifications", json={"muted": True}
    )
    assert again.json() == {"muted": True, "policy_generation": 1}

    off = client.patch(
        "/api/v1/sessions/records/u1/notifications", json={"muted": False}
    )
    assert off.json() == {"muted": False, "policy_generation": 2}
    conn.close()


def test_the_patch_route_updates_the_live_projection_too(monkeypatch, tmp_path):
    store = NotificationPolicyStore()
    store.hydrate([])
    client, conn, _ = _records_app(monkeypatch, tmp_path, store=store)
    _insert_session(conn, session_uuid="u1")

    client.patch(
        "/api/v1/sessions/records/u1/notifications", json={"muted": True}
    )

    assert store.for_uuid("u1").verdict == POLICY_MUTED
    assert store.for_instance(TMUX_NAME, TMUX_EPOCH).verdict == POLICY_MUTED
    conn.close()


def test_the_patch_route_answers_409_for_a_stale_expected_instance(
    monkeypatch, tmp_path
):
    client, conn, _ = _records_app(monkeypatch, tmp_path)
    _insert_session(conn, session_uuid="u1")

    resp = client.patch(
        "/api/v1/sessions/records/u1/notifications",
        json={
            "muted": True,
            "expected_tmux_name": TMUX_NAME,
            "expected_tmux_created_epoch": TMUX_EPOCH + 1,
        },
    )
    assert resp.status_code == 409, resp.text
    assert session_store.get_notification_policy(conn, "u1")["muted"] is False
    conn.close()


def test_the_patch_route_answers_404_for_an_unknown_row(monkeypatch, tmp_path):
    client, conn, _ = _records_app(monkeypatch, tmp_path)
    resp = client.patch(
        "/api/v1/sessions/records/ghost/notifications", json={"muted": True}
    )
    assert resp.status_code == 404
    conn.close()


def test_the_records_listing_carries_the_mute(monkeypatch, tmp_path):
    client, conn, _ = _records_app(monkeypatch, tmp_path)
    _insert_session(conn, session_uuid="u1")
    client.patch(
        "/api/v1/sessions/records/u1/notifications", json={"muted": True}
    )

    rows = client.get("/api/v1/sessions/records").json()
    row = next(r for r in rows if r["session_uuid"] == "u1")
    assert row["notifications_muted"] is True
    assert row["notification_policy_generation"] == 1
    conn.close()




def test_notifications_muted_is_on_the_wrapper_not_the_nested_session():
    from src.models import SessionInfo

    assert "notifications_muted" in SessionInfo.model_fields
    assert "notifications_muted" not in Session.model_fields
    assert SessionInfo.model_fields["notifications_muted"].default is False




def test_an_unmuted_session_on_a_startup_prompt_raises_no_toast(
    monkeypatch, tmp_path
):
    import time as _time

    from src.core.session_status import LIVENESS_LIVE
    from src.core.session_startup_gate import GATE_AWAITING

    mgr = _build_manager(
        monkeypatch, tmp_path, store=_unmuted_store(), sink=_RecordingSink()
    )
    monkeypatch.setattr(
        "src.core.session_manager.capture_pane_tail",
        lambda **kwargs: TRUST_PROMPT_TAIL,
    )
    row = {"created_at_epoch": int(_time.time()) - 600, "pid": 4321}

    verdict = mgr._startup_gate_for(
        session_id="ses_mute",
        backend=mgr._registry.backends["ses_mute"],
        tmux_name=TMUX_NAME,
        row=row,
        liveness=LIVENESS_LIVE,
    )
    assert verdict == GATE_AWAITING
    assert mgr._toast_inbox.get("ses_mute") == []
