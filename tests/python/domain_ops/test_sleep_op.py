from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import session_sleep_routes
from src.core import restart_inflight, restart_live_gate, session_sleep
from src.core.session_ops import row_probe
from src.core.session_ops import sleep as sleep_ops
from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, TmuxPresence
from tests.test_session_sleep import EPOCH, NAME, ROW_UUID, _insert, _row, state_dir  # noqa: F401


class _Servers:

    def __init__(self) -> None:
        self.cleared: list = []

    async def clear_session(self, name: str) -> None:
        self.cleared.append(name)


def _state() -> SimpleNamespace:
    return SimpleNamespace(local_servers=_Servers(), session_manager=SimpleNamespace())


def _present_then_gone(monkeypatch: pytest.MonkeyPatch, *outcomes: str) -> None:
    seen = list(outcomes)
    monkeypatch.setattr(row_probe, "socket_name", lambda: "cloude")
    monkeypatch.setattr(row_probe, "measure_presence",
                        lambda name, socket: TmuxPresence(outcome=seen.pop(0) if len(seen) > 1 else seen[0], detail="test"))

    async def close(manager: object, *, name: str, socket: str, session_id: str = None) -> dict:
        return {"closed_registrations": 1, "external": None}

    monkeypatch.setattr(session_sleep, "close_for_sleep", close)
    monkeypatch.setattr(restart_live_gate, "probe_line", lambda name, socket: f"0|{EPOCH}|{name}|$1")


def _sleep(uuid: str) -> sleep_ops.SleepOutcome:
    return asyncio.run(sleep_ops.sleep_session(_state(), uuid))


def test_a_missing_row_is_a_typed_not_found_not_an_http_error(state_dir) -> None:  # noqa: F811
    with pytest.raises(row_probe.RowNotFound) as seen:
        _sleep("no-such-uuid")
    assert not isinstance(seen.value, HTTPException)


def test_a_present_session_is_closed_and_the_row_reads_asleep(state_dir, monkeypatch) -> None:  # noqa: F811
    _insert(state_dir)
    _present_then_gone(monkeypatch, TMUX_PRESENT, TMUX_GONE)
    outcome = _sleep(ROW_UUID)
    assert (outcome.status, outcome.session_name) == ("asleep", NAME)
    assert session_sleep.is_asleep(_row(state_dir))


def test_a_declined_gate_is_an_outcome_not_an_error(state_dir, monkeypatch) -> None:  # noqa: F811
    _insert(state_dir, conv=None)
    _present_then_gone(monkeypatch, TMUX_PRESENT)
    outcome = _sleep(ROW_UUID)
    assert outcome.status == "refused" and outcome.code == session_sleep.REFUSED_NO_CONVERSATION


def test_a_socket_that_still_lists_the_name_is_sleep_still_present_and_not_marked_asleep(state_dir, monkeypatch) -> None:  # noqa: F811
    _insert(state_dir)
    _present_then_gone(monkeypatch, TMUX_PRESENT)
    with pytest.raises(sleep_ops.SleepStillPresent):
        _sleep(ROW_UUID)
    assert not session_sleep.is_asleep(_row(state_dir))


def test_a_row_in_flight_elsewhere_raises_the_inflight_error(state_dir, monkeypatch) -> None:  # noqa: F811
    _insert(state_dir)
    _present_then_gone(monkeypatch, TMUX_PRESENT, TMUX_GONE)
    with restart_inflight.claim(ROW_UUID), pytest.raises(restart_inflight.RestartInFlightError):
        _sleep(ROW_UUID)


@pytest.mark.parametrize("error, status, code", [
    (row_probe.RowNotFound("x"), 404, "session_not_found"), (row_probe.RowDatastoreUnreadable("x"), 503, "datastore_unavailable"),
    (row_probe.RowNeverHadTmux("x"), 409, "session_has_no_tmux"),
    (row_probe.RowOnRemoteHost("x"), 409, "remote_host"),
    (sleep_ops.SleepStillPresent("x"), 500, "internal_error"),
])
def test_the_route_translates_each_error_to_a_code_and_never_the_raw_text(error, status, code) -> None:
    http = session_sleep_routes.sleep_error_to_http(error)
    assert (http.status_code, http.detail["code"]) == (status, code)
    assert "x" != http.detail["detail"]


@pytest.mark.parametrize("error, status, code", [
    (row_probe.UnsafeTmuxName("x", name="bad:name"), 400, "session_name_invalid"),
    (sleep_ops.SleepFailed("x", tmux_name="n"), 500, "session_sleep_failed"),
    (restart_inflight.RestartInFlightError("x"), 409, restart_inflight.IN_PROGRESS_CODE),
])
def test_the_route_keeps_the_error_code_a_client_matches_on(error, status, code) -> None:
    http = session_sleep_routes.sleep_error_to_http(error)
    assert (http.status_code, http.detail["code"]) == (status, code)


def test_the_core_operation_raises_no_http_and_the_route_keeps_only_the_translating_facade() -> None:
    assert not hasattr(session_sleep_routes, "_record_sleep")
    assert not hasattr(session_sleep_routes, "auto_sleep_by_uuid")
    assert not issubclass(sleep_ops.SleepFailed, HTTPException)



def _real_manager(backends: dict = None) -> SimpleNamespace:
    return SimpleNamespace(_registry=SimpleNamespace(backends=backends or {}), _owned=SimpleNamespace(names=set()))


def _sleep_for_real(uuid: str, servers: "_Servers" = None) -> sleep_ops.SleepOutcome:
    state = SimpleNamespace(local_servers=servers or _Servers(), session_manager=_real_manager())
    return asyncio.run(sleep_ops.sleep_session(state, uuid))


def _live_pane(socket: str, name: str) -> tuple:
    import tempfile
    from pathlib import Path
    from src.core.tmux_backend import TmuxBackend

    backend = TmuxBackend.for_external(session_name=name, working_dir=Path(tempfile.gettempdir()), on_output=None, socket_name=socket)
    rc, _, err = backend._run_tmux_sync("new-session", "-d", "-s", name, "sh", check=False)
    assert rc == 0, err
    return _pane_facts(socket, name)


def _pane_facts(socket: str, name: str) -> tuple:
    import tempfile
    from pathlib import Path
    from src.core.tmux_backend import TmuxBackend

    backend = TmuxBackend.for_external(session_name=name, working_dir=Path(tempfile.gettempdir()), on_output=None, socket_name=socket)
    rc, out, _ = backend._run_tmux_sync("display-message", "-p", "-t", f"={name}:", "#{pane_pid}|#{session_created}", check=False)
    text = out.decode() if isinstance(out, bytes) else out
    return tuple(text.strip().split("|", 1)) if rc == 0 and "|" in text else ("", "")


@pytest.fixture
def throwaway_socket():
    import os
    import shutil
    from tests.socket_guard import derive_test_socket

    if shutil.which("tmux") is None:
        pytest.skip("tmux not on PATH")
    socket = derive_test_socket("sleep3064")
    yield socket
    os.system(f"{shutil.which('tmux')} -L {socket} kill-server >/dev/null 2>&1")


def _point_row_at(state_dir, socket: str, epoch: int) -> None:  # noqa: F811
    from contextlib import closing

    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        conn.execute("UPDATE sessions SET tmux_socket = ?, tmux_created_epoch = ? WHERE session_uuid = ?", (socket, epoch, ROW_UUID))
        conn.commit()


def test_sleep_of_a_stale_row_never_closes_a_live_pane_of_another_epoch(state_dir, throwaway_socket, monkeypatch) -> None:  # noqa: F811
    pid, epoch = _live_pane(throwaway_socket, NAME)
    _insert(state_dir)
    _point_row_at(state_dir, throwaway_socket, int(epoch) - 100)
    servers = _Servers()
    outcome = _sleep_for_real(ROW_UUID, servers)
    assert _pane_facts(throwaway_socket, NAME) == (pid, epoch)
    assert servers.cleared == []
    assert outcome.status == "asleep" and session_sleep.is_asleep(_row(state_dir))


def test_sleep_refuses_when_the_live_panes_epoch_cannot_be_matched(state_dir, throwaway_socket, monkeypatch) -> None:  # noqa: F811
    pid, epoch = _live_pane(throwaway_socket, NAME)
    _insert(state_dir)
    _point_row_at(state_dir, throwaway_socket, int(epoch))
    monkeypatch.setattr(restart_live_gate, "probe_line", lambda name, socket: None)
    outcome = _sleep_for_real(ROW_UUID)
    assert (outcome.status, outcome.code) == ("refused", session_sleep.REFUSED_PRESENCE_UNKNOWN)
    assert "creation time" in outcome.detail and "could not be listed" not in outcome.detail
    assert _pane_facts(throwaway_socket, NAME) == (pid, epoch)
    assert not session_sleep.is_asleep(_row(state_dir))


def test_sleep_still_closes_the_rows_own_live_pane(state_dir, throwaway_socket) -> None:  # noqa: F811
    _, epoch = _live_pane(throwaway_socket, NAME)
    _insert(state_dir)
    _point_row_at(state_dir, throwaway_socket, int(epoch))
    outcome = _sleep_for_real(ROW_UUID)
    assert outcome.status == "asleep"
    assert _pane_facts(throwaway_socket, NAME) == ("", "")
    assert session_sleep.is_asleep(_row(state_dir))


def _session_id(socket: str, name: str) -> str:
    import tempfile
    from pathlib import Path
    from src.core.tmux_backend import TmuxBackend

    backend = TmuxBackend.for_external(session_name=name, working_dir=Path(tempfile.gettempdir()), on_output=None, socket_name=socket)
    return asyncio.run(backend.tmux_session_id()) or ""


def test_a_newcomer_that_took_the_name_after_the_check_survives_the_close(throwaway_socket) -> None:
    _live_pane(throwaway_socket, "carnivore_keeper")
    _live_pane(throwaway_socket, NAME)
    proven = _session_id(throwaway_socket, NAME)
    assert proven.startswith("$")
    import shutil
    import subprocess
    subprocess.run([shutil.which("tmux"), "-L", throwaway_socket, "kill-session", "-t", proven], check=True)
    pid, epoch = _live_pane(throwaway_socket, NAME)
    out = asyncio.run(session_sleep.close_for_sleep(_real_manager(), name=NAME, socket=throwaway_socket, session_id=proven))
    assert out["closed_registrations"] == 0
    assert _pane_facts(throwaway_socket, NAME) == (pid, epoch)


def test_a_registration_of_a_newcomer_is_left_running_by_a_close_aimed_at_another_instance(throwaway_socket) -> None:
    class _Backend:
        tmux_session = NAME
        socket_name = throwaway_socket
        stopped = False

        async def tmux_session_id(self) -> str:
            return "$99"

        async def stop(self, kill_target=None) -> None:
            self.stopped = True

    _live_pane(throwaway_socket, "carnivore_keeper")
    backend = _Backend()
    out = asyncio.run(session_sleep.close_for_sleep(_real_manager({"ses_new": backend}), name=NAME, socket=throwaway_socket, session_id="$77"))
    assert backend.stopped is False and out["closed_registrations"] == 0


def test_an_unreadable_registration_id_stops_the_close_before_any_kill(throwaway_socket) -> None:
    class _Blind:
        tmux_session = NAME
        socket_name = throwaway_socket
        stopped = False

        async def tmux_session_id(self):
            return None

        async def stop(self, kill_target=None) -> None:
            self.stopped = True

    pid, epoch = _live_pane(throwaway_socket, NAME)
    own = _session_id(throwaway_socket, NAME)
    blind = _Blind()
    with pytest.raises(RuntimeError):
        asyncio.run(session_sleep.close_for_sleep(_real_manager({"ses_x": blind}), name=NAME, socket=throwaway_socket, session_id=own))
    assert blind.stopped is False and _pane_facts(throwaway_socket, NAME) == (pid, epoch)
