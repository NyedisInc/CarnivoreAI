
from __future__ import annotations

import json

import pytest

from src.plugins.host import developer_mode, registry_store, sideload
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401
from tests.python.cplugs.test_cplug_sideload import URL, world  # noqa: F401

HOUR = 3600


@pytest.fixture
def dev(monkeypatch):
    flag = {"on": False}
    monkeypatch.setattr(developer_mode, "is_on", lambda: flag["on"])
    return flag


def put(w, **body):
    return w.client.put(f"{URL}/switch", json=body, headers=w.owner)


def post(w):
    return w.client.post(URL, json={"path": str(w.src)}, headers=w.owner)


def test_developer_mode_off_refuses_even_with_a_live_timer(world, dev):
    w = world
    sideload.set_switch(w.state, True, lambda: w.clock.t, 24)
    assert sideload.is_on(w.state, lambda: w.clock.t)
    r = post(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sideload_off", r.text
    assert w.client.get(URL, headers=w.owner).json()["enabled"] is False


def test_turning_the_timer_on_needs_developer_mode(world, dev):
    r = put(world, enabled=True, hours=1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "developer_mode_off", r.text
    assert not sideload.is_on(world.state, lambda: world.clock.t)


def test_on_reaches_the_consent_path_then_expiry_refuses(world, dev):
    w = world
    dev["on"] = True
    r = put(w, enabled=True, hours=1)
    assert r.status_code == 200 and r.json()["developer_mode"] is True
    stored = json.loads(registry_store.registry_path(w.state).read_text())["switches"]["sideload"]
    assert stored["expires_at"] == stored["enabled_at"] + HOUR
    assert post(w).status_code == 200
    w.clock.t += HOUR
    r = post(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sideload_off", r.text


def test_a_clock_set_before_enabled_at_is_off(world, dev):
    w = world
    dev["on"] = True
    assert put(w, enabled=True, hours=None).status_code == 200
    w.clock.t -= 5
    assert not sideload.is_on(w.state, lambda: w.clock.t)
    r = post(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sideload_off", r.text
