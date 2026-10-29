
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import ui_show_routes
from src.api.auth import require_auth
from src.core.resource_push.topics import UI_SHOW
from src.core.ui_show import last_window, pointer

API = "/api/v1"
A = "tab-aaaaaaaa-1"
B = "tab-bbbbbbbb-2"
C = "tab-cccccccc-3"


@pytest.fixture
def ui(monkeypatch):
    pushed: list = []
    monkeypatch.setattr(pointer.resource_push, "notify", lambda topic: pushed.append(topic))
    last_window.reset_for_test()
    pointer.reset_for_test()
    app = FastAPI()
    app.include_router(ui_show_routes.router, prefix=API)
    app.dependency_overrides[require_auth] = lambda: True
    yield SimpleNamespace(client=TestClient(app), pushed=pushed)
    last_window.reset_for_test()
    pointer.reset_for_test()


def _active(ui, client_id: str) -> None:
    assert ui.client.post(f"{API}/ui/activity", json={"client_id": client_id}).status_code == 204


def _gone(ui, client_id: str):
    return ui.client.post(f"{API}/ui/activity/gone", json={"client_id": client_id})


def _show(ui, **body):
    return ui.client.post(f"{API}/ui/show", json={"kind": "task_manager", **body})


def _target(ui) -> str:
    return ui.client.get(f"{API}/ui/show").json()["show"]["target_client_id"]


def test_a_gone_window_falls_back_to_the_one_used_before_it_then_to_409(ui):
    _active(ui, A)
    _active(ui, B)
    assert _gone(ui, B).status_code == 204
    assert _show(ui).status_code == 200 and _target(ui) == A
    assert _gone(ui, A).status_code == 204
    pushes = len(ui.pushed)
    res = _show(ui)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "ui_show_no_window"
    assert len(ui.pushed) == pushes


def test_gone_for_an_unknown_id_is_a_quiet_204_and_a_malformed_id_is_422(ui):
    _active(ui, A)
    assert _gone(ui, B).status_code == 204
    assert last_window.current() == A
    for bad in ("short", "has space in it", "x" * 65, "../../etc/pass", ""):
        assert _gone(ui, bad).status_code == 422
    assert last_window.current() == A


def test_a_window_that_touches_again_after_gone_is_the_window_used_last(ui):
    _active(ui, A)
    _active(ui, B)
    _gone(ui, B)
    _active(ui, B)
    assert _show(ui).status_code == 200 and _target(ui) == B


def test_the_recent_list_is_bounded(ui):
    ids = [f"window-{n:04d}" for n in range(20)]
    for client_id in ids:
        last_window.touch(client_id)
    for client_id in ids[4:]:
        assert last_window.gone(client_id) is True
    assert last_window.current() is None
    assert _show(ui).status_code == 409


def test_a_show_may_name_a_known_window(ui):
    _active(ui, A)
    _active(ui, B)
    assert _show(ui, target_client_id=A).status_code == 200 and _target(ui) == A
    assert _show(ui).status_code == 200 and _target(ui) == B


def test_a_show_naming_a_window_nobody_reported_is_409_and_a_malformed_name_is_422(ui):
    _active(ui, A)
    pushes = len(ui.pushed)
    res = _show(ui, target_client_id=C)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "ui_show_no_window"
    assert _show(ui, target_client_id="short").status_code == 422
    assert len(ui.pushed) == pushes and pointer.current() is None


def test_a_gone_window_cannot_be_named(ui):
    _active(ui, A)
    _active(ui, B)
    _gone(ui, A)
    assert _show(ui, target_client_id=A).status_code == 409
    assert _ui_pushes(ui) == []


def _ui_pushes(ui) -> list:
    return [topic for topic in ui.pushed if topic == UI_SHOW]
