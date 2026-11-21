
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import mass_death_routes as routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.mass_death import detector, resume  # noqa: E402
from tests.lifecycle_helpers import conn  # noqa: E402,F401

U1, U2 = "aaaaaaaa-1111-4111-8111-111111111111", "bbbbbbbb-2222-4222-8222-222222222222"


@pytest.fixture()
def client(monkeypatch):
    woken: list = []

    async def wake(app_state, session_uuid):
        woken.append(session_uuid)
        return SimpleNamespace(status="started", tmux_session=f"carnivore_{session_uuid[:4]}", code=None)

    monkeypatch.setattr(resume, "_wake", wake)
    monkeypatch.setattr(resume, "_schedule_note", lambda *a: None)
    monkeypatch.setattr(detector, "DETECTOR", detector.MassDeathDetector())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    return SimpleNamespace(http=TestClient(app), app=app, woken=woken)


def test_route_requires_auth(client):
    client.app.dependency_overrides.clear()
    assert TestClient(client.app).post("/api/v1/sessions/mass-death/resume", json={"session_uuids": [U1]}).status_code in (401, 403)


def test_route_wakes_the_listed_sessions(client):
    response = client.http.post("/api/v1/sessions/mass-death/resume", json={"session_uuids": [U1, U2]})
    assert response.status_code == 200
    body = response.json()
    assert (body["woken"], body["refused"]) == (2, 0)
    assert sorted(client.woken) == [U1, U2]


def test_route_defaults_to_the_latest_event_and_404s_without_one(client):
    assert client.http.post("/api/v1/sessions/mass-death/resume").status_code == 404
    detector.DETECTOR.record([U1, U2, "cccccccc-3333-4333-8333-333333333333"], now=0.0)
    response = client.http.post("/api/v1/sessions/mass-death/resume")
    assert response.status_code == 200 and response.json()["woken"] == 3


def test_route_refuses_a_non_uuid_and_too_many(client):
    assert client.http.post("/api/v1/sessions/mass-death/resume", json={"session_uuids": ["nope"]}).status_code == 400
    too_many = [f"{i:08d}-0000-4000-8000-000000000000" for i in range(resume.MAX_SESSIONS + 1)]
    assert client.http.post("/api/v1/sessions/mass-death/resume", json={"session_uuids": too_many}).status_code == 422


def test_mcp_tool_is_an_act_tool_over_the_route():
    from src.core.mcp import route_adapters as ra
    from src.core.mcp.session_recovery_tools import SPECS

    (spec,) = [s for s in SPECS if s.name == "session_mass_death_resume"]
    assert spec.gate == ra.ACT and spec.route == "src.api.mass_death_routes:resume_mass_death"
    assert "wake" in spec.summary({}, None)


def _reconcile_dead(conn, names):
    from src.core.db import transaction
    from src.core.session_lifecycle import reconcile_from_listing
    from tests.lifecycle_helpers import SOCKET, add_row, live
    from tests.test_session_pane_death_reap import panes

    for n in names:
        add_row(conn, uuid=f"u-{n}", name=f"cloude_{n}", epoch=900)
    add_row(conn, uuid="u-live", name="cloude_live", epoch=1000)
    listed = [(f"cloude_{n}", 900) for n in names] + [("cloude_live", 1000)]
    status = panes(*[(f"cloude_{n}", 900, "1") for n in names], ("cloude_live", 1000, "0"))
    with transaction(conn):
        return reconcile_from_listing(conn, listing=live(*listed), socket=SOCKET, pane_status=status)


def test_the_reconciler_reports_its_pane_dead_uuids_and_feeds_the_detector(conn, monkeypatch):
    fed: list = []
    real = detector.observe
    monkeypatch.setattr(detector, "observe", lambda uuids, now=None: fed.append(list(uuids)) or real(uuids, now))
    monkeypatch.setattr(detector, "DETECTOR", detector.MassDeathDetector())
    outcome = _reconcile_dead(conn, ["a", "b", "c"])
    assert sorted(outcome.pane_dead_uuids) == ["u-a", "u-b", "u-c"]
    assert sorted(fed[-1]) == ["u-a", "u-b", "u-c"]
    assert detector.DETECTOR.last_event is not None and detector.DETECTOR.last_event.count == 3


def test_one_dead_husk_makes_no_event(conn, monkeypatch):
    monkeypatch.setattr(detector, "DETECTOR", detector.MassDeathDetector())
    _reconcile_dead(conn, ["a"])
    assert detector.DETECTOR.last_event is None
