
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pdr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pdr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.session_lifecycle import reconcile_from_listing
from src.core.session_pane_death import LIFECYCLE_SOURCE_PANE_DEAD
from src.core.session_status_map import status_map_from_listing
from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend
from tests.lifecycle_helpers import add_row, row_by_uuid
from tests import socket_guard

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

HUSK = f"{SESSION_PREFIX}pane_dead_husk"
LIVE = f"{SESSION_PREFIX}pane_dead_live"


@pytest.fixture
def tmux_socket():
    name = socket_guard.derive_test_socket("panedead")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


def _backend(name: str, socket_name: str) -> TmuxBackend:
    return TmuxBackend.for_external(
        session_name=name,
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=socket_name,
    )


def _pane_dead_for(probe: TmuxBackend, name: str):
    for row in probe.list_pane_status_all().sessions:
        if row.get("name") == name:
            return row.get("pane_dead")
    return None


def _arrange_husk_and_live(probe: TmuxBackend) -> str:
    probe._run_tmux_sync(
        "new-session", "-d", "-s", LIVE, "sleep", "600", check=False
    )
    probe._run_tmux_sync("set-option", "-g", "remain-on-exit", "on", check=False)
    rc, _, err = probe._run_tmux_sync(
        "new-session", "-d", "-s", HUSK, "sh", "-c", "exit 0", check=False
    )
    assert rc == 0, err
    raw = None
    for _ in range(50):
        raw = _pane_dead_for(probe, HUSK)
        if raw == "1":
            break
        time.sleep(0.1)
    return raw


@requires_tmux
def test_a_real_dead_pane_is_reaped_and_the_live_session_beside_it_is_not(
    tmux_socket, tmp_path
):
    probe = _backend(HUSK, tmux_socket)
    raw = _arrange_husk_and_live(probe)

    assert raw == "1", f"tmux did not report the husk's pane dead: {raw!r}"
    assert _pane_dead_for(probe, LIVE) == "0", "the control session is not alive"

    session_listing = probe.list_attachable_sessions(owned_names=set())
    assert session_listing.ok and session_listing.complete
    listed = {row["name"] for row in session_listing.sessions}
    assert HUSK in listed, (
        "remain-on-exit no longer keeps a dead session listed, which is "
        "the premise this whole rung exists for - the absence reaper "
        "would now handle it and this code would be dead"
    )
    assert LIVE in listed

    epochs = {row["name"]: row["created_at_epoch"] for row in session_listing.sessions}

    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as conn:
        add_row(
            conn,
            uuid="u-husk",
            name=HUSK,
            epoch=epochs[HUSK],
            socket=tmux_socket,
        )
        add_row(
            conn,
            uuid="u-live",
            name=LIVE,
            epoch=epochs[LIVE],
            socket=tmux_socket,
        )
        pane_status = status_map_from_listing(
            probe.list_pane_status_all(), socket=tmux_socket
        )
        with transaction(conn):
            outcome = reconcile_from_listing(
                conn,
                listing=session_listing,
                socket=tmux_socket,
                pane_status=pane_status,
            )

        assert outcome.evaluated is True
        assert outcome.stopped_uuids == ("u-husk",), (
            "exactly one row may move; reaping the live session beside it "
            "would take a session the user is working in off their list"
        )
        assert outcome.pane_dead_stopped == 1

        husk = row_by_uuid(conn, "u-husk")
        assert husk["lifecycle"] == SESSION_LIFECYCLE_STOPPED
        assert husk["lifecycle_source"] == LIFECYCLE_SOURCE_PANE_DEAD
        assert husk["archived_at"] is None

        assert row_by_uuid(conn, "u-live")["lifecycle"] == SESSION_LIFECYCLE_RUNNING

    still_listed = {
        row["name"] for row in probe.list_attachable_sessions(owned_names=set()).sessions
    }
    assert HUSK in still_listed, "the reaper killed the tmux session"
    assert LIVE in still_listed


@requires_tmux
def test_the_reap_adds_no_tmux_subprocess_of_its_own(tmux_socket, tmp_path):
    probe = _backend(HUSK, tmux_socket)
    assert _arrange_husk_and_live(probe) == "1", "arrangement"

    session_listing = probe.list_attachable_sessions(owned_names=set())
    epoch = {r["name"]: r["created_at_epoch"] for r in session_listing.sessions}[HUSK]
    pane_status = status_map_from_listing(
        probe.list_pane_status_all(), socket=tmux_socket
    )

    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as conn:
        add_row(conn, uuid="u-husk", name=HUSK, epoch=epoch, socket=tmux_socket)

        calls = []
        real_run = TmuxBackend._run_tmux_sync

        def counting(self, *args, **kwargs):
            calls.append(args)
            return real_run(self, *args, **kwargs)

        TmuxBackend._run_tmux_sync = counting
        try:
            with transaction(conn):
                outcome = reconcile_from_listing(
                    conn,
                    listing=session_listing,
                    socket=tmux_socket,
                    pane_status=pane_status,
                )
        finally:
            TmuxBackend._run_tmux_sync = real_run

    assert outcome.pane_dead_stopped == 1, "the rung did not fire, so this proves nothing"
    assert calls == [], f"the reap spawned tmux: {calls}"
