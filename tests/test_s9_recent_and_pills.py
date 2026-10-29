
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s9_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s9_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import ProbeHealth, SessionManager
from src.core.tmux_listing import TmuxListing
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_LIFECYCLE_UNKNOWN,
    SESSION_ORIGIN_OBSERVED,
)


class _StubSettings:

    def __init__(self, root: Path, port: int = 5001):
        self._root = root
        self.port = port

    def load_auth_config(self):
        raise FileNotFoundError("no config.json in this stub")

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    def get_session_metadata_path(self) -> Path:
        return self._root / "session_metadata.json"

    def get_log_directory(self) -> Path:
        return self._root / "logs"

    def get_state_dir(self) -> Path:
        return self._root

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    @property
    def default_working_dir(self) -> str:
        return str(self._root)

    @property
    def log_buffer_size(self) -> int:
        return 100

    @property
    def agents(self):
        return None


class _ProbeBackend:

    def __init__(self, rows, ok: bool = True, reason=None, detail=None):
        self._rows = rows
        self._ok = ok
        self._reason = reason
        self._detail = detail
        self.socket_name = "cloude_pytest_s9"

    def list_attachable_sessions(self, owned_names=None, owned_instances=None):
        if not self._ok:
            return TmuxListing.unavailable(self._reason, detail=self._detail)
        return TmuxListing.answered(self._rows)

    def list_pane_status_all(self):
        return TmuxListing.answered([])


def _routes_settings():
    from src.api import session_recent_routes as routes_module

    return routes_module.settings


def _manager(monkeypatch, tmp_path: Path) -> SessionManager:
    stub = _StubSettings(tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()




def _row(name="cloude_pytest_ext", epoch=1723999999, window_count=1):
    return {
        "name": name,
        "created_by_cloude": False,
        "created_at_epoch": epoch,
        "window_count": window_count,
        "tmux_session_id": "$0",
    }


def test_a_fingerprint_hit_renders_as_a_guess_not_a_fact(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend([_row()]),
    )
    monkeypatch.setattr(
        mgr, "_detect_agent_type_from_pane", lambda *, socket, name: "codex"
    )

    listing = mgr.list_attachable_sessions()

    assert listing.ok is True
    row = listing.sessions[0]
    assert row["agent_type"] == "codex"
    assert row["agent_family"] == "codex"
    assert row["agent_family_source"] == "fingerprint", (
        "a fingerprint-derived family must never render identically to a "
        f"stored fact - got source={row['agent_family_source']!r}"
    )


def test_a_fingerprint_miss_still_renders_unknown_never_default_family(
    monkeypatch, tmp_path
):
    from src.core.agent_families import DEFAULT_FAMILY

    mgr = _manager(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend([_row()]),
    )
    monkeypatch.setattr(
        mgr, "_detect_agent_type_from_pane", lambda *, socket, name: None
    )

    listing = mgr.list_attachable_sessions()

    row = listing.sessions[0]
    assert row["agent_type"] is None
    assert row["agent_family"] is None
    assert row["agent_family_source"] == "unknown"
    assert row["agent_family"] != DEFAULT_FAMILY


def test_listing_fingerprints_at_most_once_per_instance_triple(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend([_row()]),
    )
    calls = []

    def _fake_detect(*, socket, name):
        calls.append((socket, name))
        return "hermes"

    monkeypatch.setattr(mgr, "_detect_agent_type_from_pane", _fake_detect)

    first = mgr.list_attachable_sessions()
    second = mgr.list_attachable_sessions()

    assert first.ok and second.ok
    assert len(calls) == 1, (
        f"expected exactly one probe for one instance across two listing "
        f"calls, the cache should have served the second - got {len(calls)} calls"
    )
    assert second.sessions[0]["agent_family"] == "hermes"


def test_two_distinct_instances_are_fingerprinted_independently(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    rows = [_row(name="cloude_pytest_a", epoch=1000), _row(name="cloude_pytest_b", epoch=2000)]
    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend(rows),
    )
    calls = []

    def _fake_detect(*, socket, name):
        calls.append(name)
        return "codex" if name.endswith("_a") else "claude"

    monkeypatch.setattr(mgr, "_detect_agent_type_from_pane", _fake_detect)

    listing = mgr.list_attachable_sessions()
    families = {row["name"]: row["agent_family"] for row in listing.sessions}

    assert len(calls) == 2, "each distinct instance must be probed independently"
    assert families["cloude_pytest_a"] == "codex"
    assert families["cloude_pytest_b"] == "claude"


def test_probe_failure_never_crashes_listing(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend([_row()]),
    )

    def _raise(*, socket, name):
        raise RuntimeError("tmux capture-pane exploded")

    monkeypatch.setattr(mgr, "_detect_agent_type_from_pane", _raise)

    with pytest.raises(RuntimeError):
        mgr._fingerprint_agent_type_for_listing(socket="s", name="n", epoch=1)


def test_probe_health_records_ok_true_after_a_successful_listing(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    assert mgr._probe_health.health.ok is None, "must start as never-probed"
    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend([]),
    )

    listing = mgr.list_attachable_sessions()

    assert listing.ok is True
    health = mgr._probe_health.health
    assert health.ok is True
    assert health.reason is None


def test_probe_health_records_ok_false_with_reason_after_a_failed_listing(
    monkeypatch, tmp_path
):
    from src.core.tmux_listing import REASON_TIMEOUT

    mgr = _manager(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend(
            [], ok=False, reason=REASON_TIMEOUT, detail="tmux did not answer"
        ),
    )

    listing = mgr.list_attachable_sessions()

    assert listing.ok is False
    health = mgr._probe_health.health
    assert health.ok is False
    assert health.reason == REASON_TIMEOUT
    assert health.detail == "tmux did not answer"




class _HealthRecorder:

    def __init__(self, health: ProbeHealth):
        self.health = health


class _HealthManager:

    def __init__(self, health: ProbeHealth):
        self._probe_health = _HealthRecorder(health)


def _recent_client(session_manager):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router as sessions_router

    from types import SimpleNamespace

    app = FastAPI()
    app.include_router(sessions_router, prefix="/api/v1")
    app.state.session_manager = session_manager
    app.state.services = SimpleNamespace(
        probe_health=session_manager._probe_health
    )
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def test_recent_never_probed_withholds_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(
        type(_routes_settings()), "get_state_dir", lambda self: tmp_path
    )
    client = _recent_client(_HealthManager(ProbeHealth(ok=None)))
    resp = client.get("/api/v1/sessions/recent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "never_probed"
    assert body["sessions"] == []
    assert body["notice"]


def test_recent_failed_probe_withholds_rows_even_if_db_has_stopped_sessions(
    monkeypatch, tmp_path
):
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core import session_store
    from src.core.session_identity import record_instance

    monkeypatch.setattr(type(_routes_settings()), "get_state_dir", lambda self: tmp_path)
    ensure_db_migrated(tmp_path, 4, "test")
    db_path = db_path_for(tmp_path)
    conn = connect(db_path, create=True)
    try:
        record_instance(
            conn,
            socket="cloude_pytest_s9",
            name="cloude_pytest_stopped",
            epoch=1000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_STOPPED,
            lifecycle_source="tmux_missing",
        )
        conn.commit()
        stored = session_store.list_sessions(
            conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
        )
        assert len(stored) == 1, "test setup did not actually create a stopped row"
    finally:
        conn.close()

    client = _recent_client(
        _HealthManager(ProbeHealth(ok=False, reason="timeout", detail="tmux busy"))
    )
    resp = client.get("/api/v1/sessions/recent")
    body = resp.json()
    assert body["state"] == "probe_unavailable"
    assert body["sessions"] == [], (
        "a real stopped row exists in the datastore but must not be "
        f"returned while the last probe is known-failed - got {body['sessions']!r}"
    )
    assert "timeout" in body["notice"]


def test_recent_healthy_probe_returns_stored_stopped_rows(monkeypatch, tmp_path):
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.session_identity import record_instance

    monkeypatch.setattr(type(_routes_settings()), "get_state_dir", lambda self: tmp_path)
    ensure_db_migrated(tmp_path, 4, "test")
    db_path = db_path_for(tmp_path)
    conn = connect(db_path, create=True)
    try:
        record_instance(
            conn,
            socket="cloude_pytest_s9",
            name="cloude_pytest_stopped2",
            epoch=2000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_STOPPED,
            lifecycle_source="tmux_missing",
        )
        conn.commit()
    finally:
        conn.close()

    client = _recent_client(_HealthManager(ProbeHealth(ok=True)))
    resp = client.get("/api/v1/sessions/recent")
    body = resp.json()
    assert body["state"] == "ok"
    names = [s["tmux_name"] for s in body["sessions"]]
    assert "cloude_pytest_stopped2" in names
    for s in body["sessions"]:
        assert s["lifecycle"] == "stopped"


def test_recent_healthy_probe_excludes_running_and_unknown_rows(monkeypatch, tmp_path):
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.session_identity import record_instance

    monkeypatch.setattr(type(_routes_settings()), "get_state_dir", lambda self: tmp_path)
    ensure_db_migrated(tmp_path, 4, "test")
    db_path = db_path_for(tmp_path)
    conn = connect(db_path, create=True)
    try:
        record_instance(
            conn,
            socket="cloude_pytest_s9",
            name="cloude_pytest_running",
            epoch=3000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_RUNNING,
            lifecycle_source="tmux_list",
        )
        record_instance(
            conn,
            socket="cloude_pytest_s9",
            name="cloude_pytest_unknown",
            epoch=4000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_UNKNOWN,
            lifecycle_source="probe_failed",
        )
        conn.commit()
    finally:
        conn.close()

    client = _recent_client(_HealthManager(ProbeHealth(ok=True)))
    resp = client.get("/api/v1/sessions/recent")
    body = resp.json()
    assert body["state"] == "ok"
    names = [s["tmux_name"] for s in body["sessions"]]
    assert "cloude_pytest_running" not in names
    assert "cloude_pytest_unknown" not in names


def test_recent_route_defends_against_a_non_stopped_row_even_if_the_query_did_not(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(type(_routes_settings()), "get_state_dir", lambda self: tmp_path)
    (tmp_path / "carnivore.db").touch()

    def _fake_list_sessions(
        conn,
        *,
        lifecycle=None,
        include_archived=True,
        include_automated=True,
    ):
        return [
            {
                "session_uuid": "stopped-1",
                "origin": "observed",
                "lifecycle": "stopped",
                "project_attribution": "none",
            },
            {
                "session_uuid": "running-leaked",
                "origin": "observed",
                "lifecycle": "running",
                "project_attribution": "none",
            },
            {
                "session_uuid": "unknown-leaked",
                "origin": "observed",
                "lifecycle": "unknown",
                "project_attribution": "none",
            },
        ]

    monkeypatch.setattr("src.core.session_store.list_sessions", _fake_list_sessions)
    monkeypatch.setattr(
        "src.core.db.connect", lambda path, create=False, **_kw: _NullConn()
    )

    client = _recent_client(_HealthManager(ProbeHealth(ok=True)))
    resp = client.get("/api/v1/sessions/recent")
    body = resp.json()
    assert body["state"] == "ok"
    uuids = {s["session_uuid"] for s in body["sessions"]}
    assert uuids == {"stopped-1"}, (
        f"a non-stopped row leaked past the route's own defensive filter: {uuids}"
    )


class _NullConn:

    def close(self):
        return None




def test_recent_excludes_a_row_replaced_by_a_running_session(
    monkeypatch, tmp_path
):
    from src.core.db import connect, db_path_for, transaction
    from src.core.db_migration import ensure_db_migrated
    from src.core.trail_entry import utc_now

    monkeypatch.setattr(
        type(_routes_settings()), "get_state_dir", lambda self: tmp_path
    )
    ensure_db_migrated(tmp_path, 4, "test")
    conn = connect(db_path_for(tmp_path), create=True)
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO sessions (session_uuid, origin, tmux_socket,"
                " tmux_name, tmux_created_epoch, lifecycle, title,"
                " created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("s-old", "created", "cloude", "Media_Compression", 1000,
                 SESSION_LIFECYCLE_STOPPED, "Media Compression",
                 utc_now(), utc_now()),
            )
            abandoned_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO sessions (session_uuid, origin, tmux_socket,"
                " tmux_name, tmux_created_epoch, lifecycle, title,"
                " parent_session_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("s-live", "created", "cloude", "cloude_Media_Compression",
                 2000, "running", "Media Compression", abandoned_id,
                 utc_now(), utc_now()),
            )
            conn.execute(
                "INSERT INTO sessions (session_uuid, origin, tmux_socket,"
                " tmux_name, tmux_created_epoch, lifecycle, title,"
                " created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("s-done", "created", "cloude", "cloude_Old_Thing", 3000,
                 SESSION_LIFECYCLE_STOPPED, "Old Thing",
                 utc_now(), utc_now()),
            )
    finally:
        conn.close()

    client = _recent_client(_HealthManager(ProbeHealth(ok=True)))
    body = client.get("/api/v1/sessions/recent").json()
    assert body["state"] == "ok"
    names = [s["tmux_name"] for s in body["sessions"]]
    assert "Media_Compression" not in names, (
        "the abandoned row is already on screen as its running successor"
    )
    assert "cloude_Old_Thing" in names, (
        "an unrelated finished session was dropped from RECENT"
    )
    assert len(names) == 1


def test_recent_keeps_a_row_whose_successor_is_no_longer_running(
    monkeypatch, tmp_path
):
    from src.core.db import connect, db_path_for, transaction
    from src.core.db_migration import ensure_db_migrated
    from src.core.trail_entry import utc_now

    monkeypatch.setattr(
        type(_routes_settings()), "get_state_dir", lambda self: tmp_path
    )
    ensure_db_migrated(tmp_path, 4, "test")
    conn = connect(db_path_for(tmp_path), create=True)
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO sessions (session_uuid, origin, tmux_socket,"
                " tmux_name, tmux_created_epoch, lifecycle, title,"
                " created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("s-old", "created", "cloude", "Media_Compression", 1000,
                 SESSION_LIFECYCLE_STOPPED, "Media Compression",
                 utc_now(), utc_now()),
            )
            abandoned_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO sessions (session_uuid, origin, tmux_socket,"
                " tmux_name, tmux_created_epoch, lifecycle, title,"
                " parent_session_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("s-dead", "created", "cloude", "cloude_Media_Compression",
                 2000, SESSION_LIFECYCLE_STOPPED, "Media Compression",
                 abandoned_id, utc_now(), utc_now()),
            )
    finally:
        conn.close()

    client = _recent_client(_HealthManager(ProbeHealth(ok=True)))
    names = [
        s["tmux_name"]
        for s in client.get("/api/v1/sessions/recent").json()["sessions"]
    ]
    assert "Media_Compression" in names, (
        "a row was hidden even though nothing on screen represents it"
    )
    assert len(names) == 2
