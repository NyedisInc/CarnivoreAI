
from __future__ import annotations

from pathlib import Path

import pytest

from src.api import notification_mute_routes, perf_routes
from src.core.perf_hooks.monitor import PERF
from tests.python.route_tests.harness import client_for

DEVICE = "b_" + "0123456789abcdef" * 1
URL = "/notifications/mutes"


@pytest.fixture
def mute_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from src.config import settings

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "auth_config_file", str(config), raising=False)
    return client_for(notification_mute_routes.router)


def test_mute_everywhere_is_stored_and_read_back(mute_client) -> None:
    put = mute_client.put(URL, json={"type_id": "session.finished", "scope": "everywhere", "muted": True})
    assert put.status_code == 200, put.text
    assert "session.finished" in put.json()["everywhere"]
    assert "session.finished" in mute_client.get(URL).json()["everywhere"]
    off = mute_client.put(URL, json={"type_id": "session.finished", "scope": "everywhere", "muted": False})
    assert "session.finished" not in off.json()["everywhere"]


def test_mute_here_is_kept_per_device(mute_client) -> None:
    body = {"type_id": "session.finished", "scope": "here", "muted": True, "device": DEVICE}
    assert mute_client.put(URL, json=body).status_code == 200
    mine = mute_client.get(URL, params={"device": DEVICE}).json()
    assert "session.finished" in mine["here"]
    other = mute_client.get(URL, params={"device": "b_" + "f" * 16}).json()
    assert "session.finished" not in other["here"]


@pytest.mark.parametrize(
    "body,code",
    [
        ({"type_id": "no.such.type", "scope": "everywhere", "muted": True}, "unknown_type"),
        ({"type_id": "session.finished", "scope": "nowhere", "muted": True}, "bad_scope"),
        ({"type_id": "session.finished", "scope": "here", "muted": True}, "bad_device"),
        ({"type_id": "session.finished", "scope": "here", "muted": True, "device": "not-a-key"}, "bad_device"),
    ],
)
def test_mute_refusals_name_their_reason(mute_client, body: dict, code: str) -> None:
    resp = mute_client.put(URL, json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == code


def test_mutes_need_auth() -> None:
    client = client_for(notification_mute_routes.router, signed_in=False)
    assert client.get(URL).status_code in (401, 403)
    assert client.put(URL, json={"type_id": "x", "scope": "everywhere", "muted": True}).status_code in (401, 403)


@pytest.fixture
def perf_client():
    PERF.disable()
    yield client_for(perf_routes.router)
    PERF.disable()


def test_perf_switch_turns_the_hooks_on_and_off(perf_client) -> None:
    assert perf_client.get("/dev/perf").json()["enabled"] is False
    assert perf_client.put("/dev/perf", json={"enabled": True}).json()["enabled"] is True
    assert perf_client.get("/dev/perf").json()["enabled"] is True
    assert perf_client.put("/dev/perf", json={"enabled": False}).json()["enabled"] is False


def test_perf_switch_rejects_a_body_with_no_flag(perf_client) -> None:
    assert perf_client.put("/dev/perf", json={}).status_code == 422
    assert PERF.enabled is False


@pytest.mark.parametrize("body", [{"seconds": 0}, {"seconds": 100000}, {"hz": 0}, {"top": 0}])
def test_profile_rejects_a_window_outside_its_bounds(perf_client, body: dict) -> None:
    assert perf_client.post("/dev/perf/profile", json=body).status_code == 422


def test_profile_answers_the_sampler_result_and_409_while_one_runs(perf_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.perf_hooks import sampler

    async def done(request):
        return {"seconds": request.seconds, "hz": request.hz, "top": request.top}

    monkeypatch.setattr(sampler, "profile", done)
    ok = perf_client.post("/dev/perf/profile", json={"seconds": 1, "hz": 10, "top": 5})
    assert ok.status_code == 200 and ok.json() == {"seconds": 1.0, "hz": 10, "top": 5}

    async def busy(request):
        raise sampler.ProfileBusyError("a profile is already running")

    monkeypatch.setattr(sampler, "profile", busy)
    assert perf_client.post("/dev/perf/profile", json={"seconds": 1}).status_code == 409


def test_perf_routes_need_auth() -> None:
    client = client_for(perf_routes.router, signed_in=False)
    assert client.get("/dev/perf").status_code in (401, 403)
    assert client.put("/dev/perf", json={"enabled": True}).status_code in (401, 403)
    assert client.post("/dev/perf/profile", json={}).status_code in (401, 403)
    assert PERF.enabled is False
