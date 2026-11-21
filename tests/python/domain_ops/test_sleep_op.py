from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import session_sleep_routes
from src.core import restart_inflight, session_sleep
from src.core.session_ops import row_probe
from src.core.session_ops import sleep as sleep_ops
from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, TmuxPresence
from tests.test_session_sleep import NAME, ROW_UUID, _insert, _row, state_dir  # noqa: F401


class _Servers:

    async def clear_session(self, name: str) -> None:
        pass


def _state() -> SimpleNamespace:
    return SimpleNamespace(local_servers=_Servers(), session_manager=SimpleNamespace())


def _present_then_gone(monkeypatch: pytest.MonkeyPatch, *outcomes: str) -> None:
    seen = list(outcomes)
    monkeypatch.setattr(row_probe, "socket_name", lambda: "cloude")
    monkeypatch.setattr(row_probe, "measure_presence",
                        lambda name, socket: TmuxPresence(outcome=seen.pop(0) if len(seen) > 1 else seen[0], detail="test"))

    async def close(manager: object, *, name: str, socket: str) -> dict:
        return {"closed_registrations": 1, "external": None}

    monkeypatch.setattr(session_sleep, "close_for_sleep", close)


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
