
from __future__ import annotations

import os
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cow_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cow_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.config import settings  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.db_models import (  # noqa: E402
    SESSION_LIFECYCLE_RUNNING,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_identity import record_instance  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.core.session_store import owned_instances  # noqa: E402

SOCKET = "cloudecreatetest"
EPOCH = 1787000000


@pytest.fixture
def env(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    state_dir = tmp_path / "state"
    log_dir.mkdir()
    state_dir.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state_dir))
    ensure_db_migrated(state_dir, 4, "0.8.2")
    return state_dir


@pytest.fixture
def conn(env):
    with closing(connect(db_path_for(env))) as handle:
        yield handle




@pytest.mark.asyncio
async def test_created_session_badges_owned_from_the_datastore_alone(env, tmp_path):
    work = tmp_path / "wd"
    work.mkdir()
    token = uuid.uuid4().hex[:8]

    mgr = SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}",
            working_dir=str(work),
            auto_start_claude=False,
            project_name=f"cow{token}",
        )
        tmux_name = session.tmux_session
        assert tmux_name, "the created session must carry a tmux name"

        fresh = SessionManager()
        fresh._owned.names.clear()
        listing = fresh.list_attachable_sessions()
        assert listing.ok, f"tmux listing did not run: {listing.reason}"

        row = next(
            (r for r in listing.sessions if r.get("name") == tmux_name), None
        )
        assert row is not None, (
            f"{tmux_name!r} is not in the listing; the session did not survive"
        )
        assert row["created_by_cloude"] is True, (
            "a session this app created reads EXTERNAL after a restart, "
            "because no row carries origin='created'"
        )
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)


@pytest.mark.asyncio
async def test_created_session_row_carries_origin_created(env, tmp_path):
    work = tmp_path / "wd"
    work.mkdir()
    token = uuid.uuid4().hex[:8]

    mgr = SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}",
            working_dir=str(work),
            auto_start_claude=False,
            project_name=f"cow{token}",
        )
        with closing(connect(db_path_for(env))) as handle:
            rows = handle.execute(
                "SELECT origin, lifecycle, tmux_created_epoch FROM sessions"
                " WHERE tmux_name = ?",
                (session.tmux_session,),
            ).fetchall()
        assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
        assert rows[0]["origin"] == SESSION_ORIGIN_CREATED
        assert rows[0]["lifecycle"] == SESSION_LIFECYCLE_RUNNING
        assert rows[0]["tmux_created_epoch"] is not None
        assert session.tmux_created_epoch == rows[0]["tmux_created_epoch"]
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)


@pytest.mark.asyncio
async def test_creating_is_idempotent_across_a_repeat_record(env, tmp_path):
    work = tmp_path / "wd"
    work.mkdir()
    token = uuid.uuid4().hex[:8]

    mgr = SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}",
            working_dir=str(work),
            auto_start_claude=False,
            project_name=f"cow{token}",
        )
        name = session.tmux_session
        second = mgr.persist_creation(name)
        assert second.outcome in ("recorded", "merged"), second.outcome

        with closing(connect(db_path_for(env))) as handle:
            rows = handle.execute(
                "SELECT origin FROM sessions WHERE tmux_name = ?", (name,)
            ).fetchall()
        assert len(rows) == 1, f"re-recording duplicated the row: {len(rows)}"
        assert rows[0]["origin"] == SESSION_ORIGIN_CREATED
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)




def test_a_created_row_is_not_demoted_by_a_later_observed_sighting(conn):
    name = "cloude_promote_created"
    record_instance(
        conn,
        socket=SOCKET,
        name=name,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_CREATED,
        lifecycle_source="create",
        session_id="$1",
    )
    conn.commit()

    after = record_instance(
        conn,
        socket=SOCKET,
        name=name,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_OBSERVED,
        lifecycle_source="reconcile",
        session_id="$1",
    )
    conn.commit()
    assert after.outcome == "merged", after.outcome

    row = conn.execute(
        "SELECT origin FROM sessions WHERE tmux_name = ?", (name,)
    ).fetchone()
    assert row["origin"] == SESSION_ORIGIN_CREATED, (
        "a reconcile demoted a created session to observed"
    )
    assert (name, EPOCH) in owned_instances(conn, socket=SOCKET)


def test_an_adopted_row_is_not_demoted_by_a_later_created_sighting(conn):
    name = "cloude_promote_adopted"
    record_instance(
        conn,
        socket=SOCKET,
        name=name,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_ADOPTED,
        lifecycle_source="adopt",
        session_id="$2",
    )
    conn.commit()

    after = record_instance(
        conn,
        socket=SOCKET,
        name=name,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_CREATED,
        lifecycle_source="create",
        session_id="$2",
    )
    conn.commit()
    assert after.outcome == "merged", after.outcome

    row = conn.execute(
        "SELECT origin FROM sessions WHERE tmux_name = ?", (name,)
    ).fetchone()
    assert row["origin"] == SESSION_ORIGIN_ADOPTED




@pytest.mark.asyncio
async def test_a_restart_and_reconcile_leave_a_created_session_ours(env, tmp_path):
    work = tmp_path / "wd"
    work.mkdir()
    token = uuid.uuid4().hex[:8]

    mgr = SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}",
            working_dir=str(work),
            auto_start_claude=False,
            project_name=f"cow{token}",
        )
        name = session.tmux_session

        fresh = SessionManager()
        fresh._owned.names.clear()

        listing = fresh.list_attachable_sessions()
        assert listing.ok, f"tmux listing did not run: {listing.reason}"
        outcome = fresh.reconcile_lifecycle(listing)
        assert outcome is not None

        with closing(connect(db_path_for(env))) as handle:
            rows = handle.execute(
                "SELECT origin FROM sessions WHERE tmux_name = ?", (name,)
            ).fetchall()
        assert len(rows) == 1, f"the reconcile duplicated the row: {len(rows)}"
        assert rows[0]["origin"] == SESSION_ORIGIN_CREATED, (
            "the reconciler demoted a created session"
        )

        after = SessionManager()
        after._owned.names.clear()
        relisting = after.list_attachable_sessions()
        assert relisting.ok
        row = next(
            (r for r in relisting.sessions if r.get("name") == name), None
        )
        assert row is not None and row["created_by_cloude"] is True
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)


def test_an_adopted_row_survives_the_reconcile_write_verbatim(conn):
    name = "cloude_adopt_survives"
    record_instance(
        conn,
        socket=SOCKET,
        name=name,
        epoch=EPOCH,
        origin=SESSION_ORIGIN_ADOPTED,
        lifecycle_source="adopt",
        session_id="$7",
    )
    conn.commit()

    for source in ("reconcile", "poll", "create"):
        record_instance(
            conn,
            socket=SOCKET,
            name=name,
            epoch=EPOCH,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle_source=source,
            session_id="$7",
        )
    conn.commit()

    row = conn.execute(
        "SELECT origin FROM sessions WHERE tmux_name = ?", (name,)
    ).fetchone()
    assert row["origin"] == SESSION_ORIGIN_ADOPTED
    assert (name, EPOCH) in owned_instances(conn, socket=SOCKET)
