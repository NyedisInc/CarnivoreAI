
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sleep_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sleep_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import recreate_routes, session_sleep_routes
from src.api.auth import require_auth
from src.core import session_sleep
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.session_recreate_presence import (
    TMUX_GONE,
    TMUX_PRESENT,
    TMUX_UNKNOWN,
    TmuxPresence,
)

NAME = "carnivore_sleep_demo"
ROW_UUID = "row-uuid-sleep"
CONV_UUID = "11111111-2222-3333-4444-555555555555"
EPOCH = 1790090835


def _running_row(**overrides):
    row = {
        "session_uuid": ROW_UUID,
        "tmux_name": NAME,
        "tmux_created_epoch": EPOCH,
        "lifecycle": "running",
        "lifecycle_source": "tmux_list",
        "archived_at": None,
        "claude_session_uuid": CONV_UUID,
    }
    row.update(overrides)
    return row




def test_a_running_session_with_a_conversation_may_sleep():
    assert session_sleep.sleep_refusal(_running_row()) is None


def test_no_conversation_id_refuses_with_a_sentence():
    refusal = session_sleep.sleep_refusal(_running_row(claude_session_uuid=None))
    assert refusal is not None and refusal.code == session_sleep.REFUSED_NO_CONVERSATION
    assert "conversation" in refusal.detail and "nothing was stopped" in refusal.detail


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"archived_at": "2026-09-01T00:00:00Z"}, session_sleep.REFUSED_ARCHIVED),
        ({"tmux_name": None}, session_sleep.REFUSED_NO_TMUX),
        ({"tmux_created_epoch": None}, session_sleep.REFUSED_NO_TMUX),
        ({"lifecycle": "stopped"}, session_sleep.REFUSED_NOT_RUNNING),
    ],
)
def test_each_other_gate_refuses(overrides, code):
    refusal = session_sleep.sleep_refusal(_running_row(**overrides))
    assert refusal is not None and refusal.code == code


def test_is_asleep_needs_all_three_facts():
    asleep = _running_row(lifecycle="stopped", lifecycle_source="slept_by_user")
    assert session_sleep.is_asleep(asleep)
    assert not session_sleep.is_asleep({**asleep, "lifecycle_source": "closed_by_user"})
    assert not session_sleep.is_asleep({**asleep, "archived_at": "2026-09-01T00:00:00Z"})
    assert not session_sleep.is_asleep({**asleep, "lifecycle": "running"})
    assert not session_sleep.is_asleep(None)




def _insert(state_dir, *, lifecycle="running", source="tmux_list", conv=CONV_UUID,
            uuid=ROW_UUID, name=NAME, agent_type="claude"):
    with connect(db_path_for(state_dir), create=False) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
            "tmux_created_epoch, working_dir, claude_session_uuid, title, "
            "origin, lifecycle, lifecycle_source, agent_type, created_at, "
            "updated_at) VALUES (?, 'cloude', ?, ?, '/Users/x/proj', ?, "
            "'fix the deploy', 'created', ?, ?, ?, '2026-09-01T00:00:00Z', "
            "'2026-09-01T00:00:00Z')",
            (uuid, name, EPOCH, conv, lifecycle, source, agent_type),
        )
        return int(cur.lastrowid)


def _row(state_dir, uuid=ROW_UUID):
    with connect(db_path_for(state_dir), create=False) as conn:
        return dict(conn.execute(
            "SELECT * FROM sessions WHERE session_uuid = ?", (uuid,)
        ).fetchone())


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    from src.config import settings

    sd = tmp_path / "state"
    sd.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: sd, raising=True)
    assert ensure_db_migrated(sd).status == "ok"
    return sd


def test_mark_asleep_keeps_the_conversation_and_writes_over_the_reaper(state_dir):
    row_id = _insert(state_dir, lifecycle="stopped", source="tmux_missing")
    with connect(db_path_for(state_dir), create=False) as conn:
        moved = session_sleep.mark_asleep(
            conn, row_id=row_id, tmux_name=NAME, tmux_created_epoch=EPOCH
        )
    assert moved == 1
    row = _row(state_dir)
    assert session_sleep.is_asleep(row)
    assert row["claude_session_uuid"] == CONV_UUID


def test_mark_asleep_never_writes_a_rebound_instance(state_dir):
    row_id = _insert(state_dir)
    with connect(db_path_for(state_dir), create=False) as conn:
        moved = session_sleep.mark_asleep(
            conn, row_id=row_id, tmux_name=NAME, tmux_created_epoch=EPOCH + 1
        )
    assert moved == 0
    assert _row(state_dir)["lifecycle"] == "running"


def test_the_recreate_rebind_clears_the_marker(state_dir):
    from src.core.session_restart import rebind_instance

    row_id = _insert(state_dir, lifecycle="stopped", source="slept_by_user")
    assert session_sleep.is_asleep(_row(state_dir))
    with connect(db_path_for(state_dir), create=False) as conn:
        assert rebind_instance(
            conn, row_id=row_id, socket="cloude", name=NAME, epoch=EPOCH + 5,
            lifecycle_source="tmux_list",
        ).rebound
    row = _row(state_dir)
    assert not session_sleep.is_asleep(row)
    assert row["claude_session_uuid"] == CONV_UUID




class _LocalServers:
    def __init__(self):
        self.cleared = []

    async def clear_session(self, name):
        self.cleared.append(name)


@pytest.fixture()
def client(state_dir, monkeypatch):
    from src.api import session_records_routes, session_recent_routes

    monkeypatch.setattr(recreate_routes, "_socket_name", lambda: "cloude", raising=True)
    closes = []

    async def _close(manager, *, name, socket):
        closes.append((name, socket))
        return {"closed_registrations": 1, "external": None}

    monkeypatch.setattr(session_sleep, "close_for_sleep", _close, raising=True)
    app = FastAPI()
    app.include_router(session_sleep_routes.router, prefix="/api/v1")
    app.include_router(session_recent_routes.router, prefix="/api/v1")
    app.include_router(session_records_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.local_servers = _LocalServers()
    app.state.session_manager = SimpleNamespace()
    app.state.services = SimpleNamespace(
        probe_health=SimpleNamespace(health=SimpleNamespace(ok=True, reason=None))
    )
    with TestClient(app) as c:
        yield c, closes


def _presence(monkeypatch, *outcomes):
    seen = list(outcomes)

    def _measure(name, socket):
        outcome = seen.pop(0) if len(seen) > 1 else seen[0]
        return TmuxPresence(outcome=outcome, detail="test")

    monkeypatch.setattr(recreate_routes, "_measure_presence", _measure, raising=True)


def test_sleep_closes_a_present_session_and_keeps_its_row_asleep(state_dir, client, monkeypatch):
    c, closes = client
    _insert(state_dir)
    _presence(monkeypatch, TMUX_PRESENT, TMUX_GONE)

    r = c.post(f"/api/v1/sessions/{ROW_UUID}/sleep")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "asleep"
    assert closes == [(NAME, "cloude")]
    assert session_sleep.is_asleep(_row(state_dir))

    asleep = c.get("/api/v1/sessions/asleep").json()
    assert [a["session_uuid"] for a in asleep] == [ROW_UUID]
    assert asleep[0]["asleep"] is True
    records = c.get("/api/v1/sessions/records").json()
    assert [x["asleep"] for x in records if x["session_uuid"] == ROW_UUID] == [True]
    recent = c.get("/api/v1/sessions/recent").json()
    assert recent["state"] == "ok"
    assert ROW_UUID not in [x["session_uuid"] for x in recent["sessions"]], (
        "an asleep row stays in the running lists; a session appears in "
        "exactly one list"
    )


def test_a_closed_row_still_lists_in_recent(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="closed_by_user")
    recent = c.get("/api/v1/sessions/recent").json()
    assert [x["session_uuid"] for x in recent["sessions"]] == [ROW_UUID]
    assert c.get("/api/v1/sessions/asleep").json() == []


def test_a_close_the_socket_still_lists_is_not_marked_asleep(state_dir, client, monkeypatch):
    c, closes = client
    _insert(state_dir)
    _presence(monkeypatch, TMUX_PRESENT, TMUX_PRESENT)
    r = c.post(f"/api/v1/sessions/{ROW_UUID}/sleep")
    assert r.status_code == 500
    assert closes == [(NAME, "cloude")]
    assert not session_sleep.is_asleep(_row(state_dir))


def test_an_asleep_name_stays_reserved_against_a_fresh_create(state_dir):
    from src.core.session_name_claim import claim_tmux_name
    from src.core.tmux_listing import TmuxListing

    _insert(state_dir, lifecycle="stopped", source="slept_by_user")
    reserved = session_sleep.reserved_names(set())
    assert NAME in reserved
    fresh = claim_tmux_name(NAME, listing=TmuxListing.answered([]), active_names=(),
                            owned_names=reserved, recreate=False)
    assert fresh.name == f"{NAME}-2"
    woken = claim_tmux_name(NAME, listing=TmuxListing.answered([]), active_names=(),
                            owned_names=reserved, recreate=True)
    assert woken.name == NAME
    with connect(db_path_for(state_dir), create=False) as conn:
        conn.execute("UPDATE sessions SET lifecycle_source = 'closed_by_user'")
    assert NAME not in session_sleep.reserved_names(set())


def test_sleep_refuses_without_a_conversation_and_closes_nothing(state_dir, client, monkeypatch):
    c, closes = client
    _insert(state_dir, conv=None)
    _presence(monkeypatch, TMUX_PRESENT)
    body = c.post(f"/api/v1/sessions/{ROW_UUID}/sleep").json()
    assert body["status"] == "refused" and body["code"] == "no_conversation"
    assert closes == []
    assert _row(state_dir)["lifecycle"] == "running"


def test_sleep_refuses_an_unmeasured_socket(state_dir, client, monkeypatch):
    c, closes = client
    _insert(state_dir)
    _presence(monkeypatch, TMUX_UNKNOWN)
    body = c.post(f"/api/v1/sessions/{ROW_UUID}/sleep").json()
    assert body["status"] == "refused" and body["code"] == "presence_unknown"
    assert closes == []
    assert not session_sleep.is_asleep(_row(state_dir))


def test_sleep_of_an_already_gone_session_only_marks_it(state_dir, client, monkeypatch):
    c, closes = client
    _insert(state_dir)
    _presence(monkeypatch, TMUX_GONE)
    assert c.post(f"/api/v1/sessions/{ROW_UUID}/sleep").json()["status"] == "asleep"
    assert closes == []
    assert session_sleep.is_asleep(_row(state_dir))


def test_sleep_of_an_unknown_uuid_is_a_404(client):
    c, _ = client
    assert c.post("/api/v1/sessions/nope/sleep").status_code == 404


def test_wake_refuses_a_row_that_is_not_asleep(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="closed_by_user")
    called = []

    async def _recreate(*a, **kw):
        called.append(a)

    monkeypatch.setattr("src.api.recreate_action.recreate_by_uuid", _recreate)
    r = c.post(f"/api/v1/sessions/{ROW_UUID}/wake")
    assert r.status_code == 409
    assert called == []


def test_wake_runs_the_recreate_action_under_the_rows_own_wrapper(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="slept_by_user", agent_type="claude-skip")
    monkeypatch.setattr("src.core.session_agent_choice.configured_wrapper_ids",
                        lambda settings_obj: ["claude-skip", "keyc"])
    called = []

    async def _recreate(session_uuid, agent_type, *, get_manager, row_overrides=None):
        called.append((session_uuid, agent_type))
        return recreate_routes.RecreateResponse(
            status="started", session_uuid=session_uuid, session_name=NAME,
            presence="gone", conversation="resumed", detail="resumed",
        )

    monkeypatch.setattr("src.api.recreate_action.recreate_by_uuid", _recreate)
    r = c.post(f"/api/v1/sessions/{ROW_UUID}/wake")
    assert r.status_code == 200, r.text
    assert r.json()["conversation"] == "resumed"
    assert called == [(ROW_UUID, "claude-skip")]



requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")


@requires_tmux
def test_the_close_kills_exactly_its_name_and_drops_the_registration():
    from src.core.tmux_backend import TmuxBackend
    from tests.socket_guard import derive_test_socket

    socket = derive_test_socket("sleep")
    name = "carnivore_sleep_probe"
    twin = name + "-2"

    def backend(n):
        return TmuxBackend.for_external(
            session_name=n, working_dir=Path(tempfile.gettempdir()),
            on_output=None, socket_name=socket,
        )

    try:
        for n in (name, twin):
            rc, _, err = backend(n)._run_tmux_sync("new-session", "-d", "-s", n, "sh", check=False)
            assert rc == 0, err
        live = backend(name)
        live._running = True
        wiped, released = [], []
        manager = SimpleNamespace(
            _registry=SimpleNamespace(backends={"ses_a": live}),
            _owned=SimpleNamespace(names={name}),
            _save_session_metadata=lambda: None,
            hook_tokens=SimpleNamespace(release=lambda sid, tmux_name: released.append((sid, tmux_name))),
        )
        manager._wipe_session_state = lambda sid: (wiped.append(sid), manager._registry.backends.pop(sid, None))

        out = asyncio.run(session_sleep.close_for_sleep(manager, name=name, socket=socket))
        assert out["closed_registrations"] == 1
        assert wiped == ["ses_a"] and released == [("ses_a", name)]
        assert name not in manager._owned.names

        listing = backend(twin).discover_existing()
        assert listing.ok
        names = list(listing.sessions or [])
        assert twin in names, "the prefix twin was killed with it"
        assert name not in names, "the slept session is still on the socket"
    finally:
        os.system(f"{shutil.which('tmux')} -L {socket} kill-server >/dev/null 2>&1")


@requires_tmux
def test_with_no_registration_the_close_kills_exactly_its_name_on_the_rows_socket():
    from src.core.tmux_backend import TmuxBackend
    from tests.socket_guard import derive_test_socket

    socket = derive_test_socket("sleep-direct")
    name = "carnivore_sleep_direct"
    twin = name + "-2"

    def backend(n):
        return TmuxBackend.for_external(
            session_name=n, working_dir=Path(tempfile.gettempdir()),
            on_output=None, socket_name=socket,
        )

    try:
        for n in (name, twin):
            rc, _, err = backend(n)._run_tmux_sync("new-session", "-d", "-s", n, "sh", check=False)
            assert rc == 0, err
        manager = SimpleNamespace(
            _registry=SimpleNamespace(backends={}),
            _owned=SimpleNamespace(names={name}),
            _save_session_metadata=lambda: None,
        )
        out = asyncio.run(session_sleep.close_for_sleep(manager, name=name, socket=socket))
        assert out == {"closed_registrations": 0, "direct_kill_rc": 0}
        names = list(backend(twin).discover_existing().sessions or [])
        assert twin in names and name not in names
        assert name not in manager._owned.names
        again = asyncio.run(session_sleep.close_for_sleep(manager, name=name, socket=socket))
        assert again["direct_kill_rc"] != 0
    finally:
        os.system(f"{shutil.which('tmux')} -L {socket} kill-server >/dev/null 2>&1")
