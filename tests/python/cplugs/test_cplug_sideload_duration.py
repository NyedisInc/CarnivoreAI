
from __future__ import annotations

import asyncio
import json

import pytest

from src.cplugs.host import sideload
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401
from tests.python.cplugs.test_cplug_sideload import URL, world  # noqa: F401

HOUR = 3600


def put(w, **body):
    return w.client.put(f"{URL}/switch", json=body, headers=w.owner)


@pytest.mark.parametrize("hours", [1, 12, 24, 168])
def test_each_allowed_duration_ends_on_time(world, hours):
    w = world
    r = put(w, enabled=True, hours=hours)
    assert r.status_code == 200, r.text
    assert r.json()["expires_at"] == w.clock.t + hours * HOUR and r.json()["hours"] == hours
    w.clock.t += hours * HOUR - 1
    assert sideload.is_on(w.state)
    w.clock.t += 1
    assert not sideload.is_on(w.state)


def test_omitted_is_twelve_hours_and_null_is_until_turned_off(world):
    w = world
    r = put(w, enabled=True)
    assert r.json()["expires_at"] == w.clock.t + 12 * HOUR and r.json()["hours"] == 12
    r = put(w, enabled=True, hours=None)
    body = r.json()
    assert r.status_code == 200 and body["enabled"] is True and body["expires_at"] is None and body["hours"] is None
    w.clock.t += 10 * 365 * 24 * HOUR
    assert sideload.is_on(w.state) and w.client.get(URL, headers=w.owner).json()["enabled"] is True
    off = put(w, enabled=False).json()
    assert off["enabled"] is False and off["hours"] is None
    assert not sideload.is_on(w.state)


@pytest.mark.parametrize("bad", [2, 0, -1, 12.0, "12", True, [12], 169])
def test_any_other_duration_is_refused_and_changes_nothing(world, bad):
    w = world
    r = put(w, enabled=True, hours=bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "duration_invalid", r.text
    assert not sideload.is_on(w.state)


def test_a_file_without_the_field_keeps_twelve_hours(world):
    w = world
    path = sideload.switch_path(w.state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled_at": w.clock.t, "items": {}}))
    assert sideload.expires_at(w.state) == w.clock.t + 12 * HOUR
    w.clock.t += 12 * HOUR - 1
    assert sideload.is_on(w.state)
    w.clock.t += 1
    assert not sideload.is_on(w.state)


def test_until_turned_off_arms_no_timer_at_boot_and_a_later_duration_arms_one(world, monkeypatch):
    from src.cplugs.host import sideload_routes
    from src.main import app

    w = world
    assert put(w, enabled=True, hours=None).status_code == 200
    app.state.sideload_expiry = None
    stopped = []

    async def fake_stop_all(live):
        stopped.append(live)

    monkeypatch.setattr(sideload_routes, "stop_all_local", fake_stop_all)

    async def boot_then_wait():
        await w.rt.start()
        assert app.state.sideload_expiry is None
        w.clock.t += 365 * 24 * HOUR
        await sideload_routes._expired(w.rt)
        sideload.set_switch(w.state, True, sideload.wall, 1)
        sideload_routes.arm_expiry(app, w.rt)
        handle = app.state.sideload_expiry
        assert handle is not None
        handle.cancel()

    asyncio.run(boot_then_wait())
    assert stopped == []
