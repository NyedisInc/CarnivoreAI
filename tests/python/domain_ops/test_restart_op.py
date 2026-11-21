from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import session_restart_apply_routes as routes
from src.core import restart_inflight, restart_live_gate, session_restart
from src.core.automations.recipes import RecipeFailed
from src.core.automations import system_actions
from src.core.hosts.remote_restart import RemoteRestartRefused
from src.core.session_ops import restart as restart_ops


def _source(outcome: str) -> session_restart.RestartSource:
    return session_restart.RestartSource(outcome, parent_id=26, working_dir="/tmp", agent_type="claude", title="Shopify")


def _run(tmp_path, monkeypatch: pytest.MonkeyPatch, outcome: str, running: bool = False, datastore: bool = True) -> tuple:
    if datastore:
        (tmp_path / "carnivore.db").write_bytes(b"")
    monkeypatch.setattr(type(restart_ops.settings), "get_state_dir", lambda self: tmp_path)
    monkeypatch.setattr(session_restart, "resolve_restart_source", lambda conn, session_uuid, **kw: _source(outcome))
    monkeypatch.setattr(restart_live_gate, "bound_instance_running", lambda *a: running)
    calls: list = []

    async def no_account(config_path, *, session_uuid, family):
        return SimpleNamespace(account_id=None)

    monkeypatch.setattr(restart_ops.restart_account, "resolve", no_account)
    monkeypatch.setattr(restart_ops.restart_account, "family_of", lambda agent_type: "claude")
    monkeypatch.setattr(restart_ops.restart_seam, "check_relaunch", lambda *a: None)

    async def create(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop after the spawn decision")

    return calls, SimpleNamespace(session_manager=SimpleNamespace(create_session=create))


def _go(state, uuid: str = "row-26"):
    return asyncio.run(restart_ops.restart_stopped_session(state, uuid))


def test_no_datastore_is_a_typed_not_found(monkeypatch, tmp_path) -> None:
    _, state = _run(tmp_path, monkeypatch, session_restart.RESTART_RESUMABLE, datastore=False)
    with pytest.raises(restart_ops.NoDatastore) as seen:
        _go(state)
    assert not isinstance(seen.value, HTTPException)


def test_an_unresolved_row_is_restart_source_not_found(monkeypatch, tmp_path) -> None:
    _, state = _run(tmp_path, monkeypatch, session_restart.RESTART_UNRESOLVED)
    with pytest.raises(restart_ops.RestartSourceNotFound):
        _go(state)


def test_a_running_row_is_already_running_and_spawns_nothing(monkeypatch, tmp_path) -> None:
    calls, state = _run(tmp_path, monkeypatch, session_restart.RESTART_NO_CONVERSATION, running=True)
    with pytest.raises(restart_ops.AlreadyRunning):
        _go(state)
    assert calls == []


def test_a_conversation_not_on_disk_spawns_nothing(monkeypatch, tmp_path) -> None:
    calls, state = _run(tmp_path, monkeypatch, session_restart.RESTART_CONVERSATION_MISSING)
    with pytest.raises(restart_ops.ConversationMissing):
        _go(state)
    assert calls == []


def test_a_failed_create_is_replacement_create_failed(monkeypatch, tmp_path) -> None:
    calls, state = _run(tmp_path, monkeypatch, session_restart.RESTART_NO_CONVERSATION)
    with pytest.raises(restart_ops.ReplacementCreateFailed):
        _go(state)
    assert len(calls) == 1


def test_a_lost_race_to_an_adoption_is_row_taken_over_not_a_failed_create(monkeypatch, tmp_path) -> None:
    from src.core.sessions.reuse_guard import ReuseRowTakenError

    calls, state = _run(tmp_path, monkeypatch, session_restart.RESTART_NO_CONVERSATION)

    async def lost(**kwargs):
        calls.append(kwargs)
        raise ReuseRowTakenError(26, "carnivore_adopted")

    state.session_manager.create_session = lost
    with pytest.raises(restart_ops.RowTakenOver) as seen:
        _go(state)
    assert seen.value.held_tmux_name == "carnivore_adopted"
    http = routes.restart_error_to_http(seen.value, "row-26")
    assert (http.status_code, http.detail["code"]) == (409, "row_taken_over")


@pytest.mark.parametrize("error, status, code", [
    (restart_ops.NoDatastore("no datastore yet"), 404, "not_found"),
    (restart_ops.RestartSourceNotFound("gone"), 404, "not_found"),
    (restart_ops.ConversationMissing("not on disk"), 409, "conflict"),
    (restart_ops.AlreadyRunning("this session is already running"), 409, restart_live_gate.ALREADY_RUNNING_CODE),
])
def test_the_route_answers_a_code_and_a_fixed_sentence_for_each_refusal(error, status, code) -> None:
    http = routes.restart_error_to_http(error, "row-26")
    assert (http.status_code, http.detail["code"]) == (status, code)
    assert http.detail["detail"] != str(error)


@pytest.mark.parametrize("error, status, code", [
    (restart_ops.RestartDatastoreUnreadable("x"), 503, "datastore_unavailable"),
    (restart_ops.ReplacementCreateFailed("x", replaced_session_uuid="row-26", label="L"), 500, "session_restart_failed"),
    (restart_inflight.RestartInFlightError("row-26"), 409, restart_inflight.IN_PROGRESS_CODE),
])
def test_the_route_keeps_the_error_codes_a_client_matches_on(error, status, code) -> None:
    http = routes.restart_error_to_http(error, "row-26")
    assert (http.status_code, http.detail["code"]) == (status, code)


def test_a_remote_refusal_keeps_its_hosts_own_status_and_code() -> None:
    refusal = RemoteRestartRefused(409, "far_gone", "gone")
    failed = restart_ops.RemoteRestartFailed("gone", "studio")
    failed.__cause__ = refusal
    http = routes.restart_error_to_http(failed, "row-26")
    assert (http.status_code, http.detail["code"]) == (409, "far_gone")


def test_the_automation_recipe_reads_the_class_not_a_status_number(monkeypatch) -> None:
    async def refuse(app_state, session_uuid):
        raise restart_ops.RestartSourceNotFound("no row")

    async def find_live(ops, uuid):
        return None

    from src.core.session_delivery import bring_up
    monkeypatch.setattr(bring_up, "ops_for_app", lambda s: None)
    monkeypatch.setattr(bring_up, "find_live", find_live)
    monkeypatch.setattr(restart_ops, "restart_stopped_session", refuse)
    ctx = SimpleNamespace(app_state=SimpleNamespace())
    with pytest.raises(RecipeFailed):
        asyncio.run(system_actions.restart_session(ctx, system_actions.RestartParams(session_uuid="0f6c2d6e-1111-4c4c-9e9e-000000000002")))
