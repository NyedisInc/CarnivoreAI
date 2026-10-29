
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Iterator, List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_reap_order_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_reap_order_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.db_models import SESSION_LIFECYCLE_RUNNING, SESSION_LIFECYCLE_STOPPED
from src.core.session_manager import SessionManager
from src.core.session_pane_death import LIFECYCLE_SOURCE_PANE_DEAD
from tests.lifecycle_helpers import add_row, row_by_uuid
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

HUSK = "carnivore_reap_order_husk"
LIVE = "carnivore_reap_order_live"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=False)


def _wait_pane_dead(name: str, want: str) -> bool:
    for _ in range(50):
        if _tmux("display-message", "-p", "-t", f"={name}:", "#{pane_dead}").stdout.strip() == want:
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def husk_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmux_test_socket: str) -> Iterator[Path]:
    state = tmp_path / "state"
    logs = tmp_path / "logs"
    state.mkdir()
    logs.mkdir()
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    monkeypatch.setattr(settings, "log_directory", str(logs))
    try:
        assert _tmux("new-session", "-d", "-s", LIVE, "sleep 600").returncode == 0
        _tmux("set-option", "-g", "remain-on-exit", "on")
        assert _tmux("new-session", "-d", "-s", HUSK, "sh -c 'exit 0'").returncode == 0
        assert _wait_pane_dead(HUSK, "1"), "arrangement: the husk's pane never read dead"
        epoch = int(_tmux("display-message", "-p", "-t", f"={HUSK}:", "#{session_created}").stdout)
        with closing(migrated_connection(state)) as conn:
            add_row(conn, uuid="u-husk", name=HUSK, epoch=epoch, socket=TEST_SOCKET_NAME)
        yield state
    finally:
        _tmux("kill-server")


@requires_tmux
def test_a_husk_restarted_during_the_pass_is_not_stopped_from_the_older_pane_map(
        husk_row: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = SessionManager()
    real = manager.reconcile_lifecycle
    calls: List[bool] = []
    respawned: List[bool] = []

    def delayed(listing, pane_status: Optional[object] = None):
        calls.append(pane_status is not None)
        if pane_status is None:
            assert _tmux("respawn-pane", "-k", "-t", f"={HUSK}:", "sleep 600").returncode == 0
            assert _wait_pane_dead(HUSK, "0"), "the husk did not come back alive"
            respawned.append(True)
        return real(listing, pane_status)

    monkeypatch.setattr(manager, "reconcile_lifecycle", delayed)
    listing = manager.list_attachable_sessions()
    assert listing.ok

    with closing(migrated_connection(husk_row)) as conn:
        row = row_by_uuid(conn, "u-husk")
    if respawned:
        assert row["lifecycle"] == SESSION_LIFECYCLE_RUNNING, (
            "a pane map read before the restart stopped the restarted session "
            f"(lifecycle_source={row['lifecycle_source']!r})")
    assert calls == [True], f"one reconcile per pass, carrying the pane map; got {calls}"
    assert row["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert row["lifecycle_source"] == LIFECYCLE_SOURCE_PANE_DEAD
