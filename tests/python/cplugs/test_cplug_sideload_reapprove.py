
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.cplugs.host import owner_switch, sidecar_registry
from src.cplugs.host import state as owner_state
from src.cplugs.runtime.supervisor import Supervisor
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401
from tests.python.cplugs.test_cplug_sideload import NAME, URL, post, world  # noqa: F401

CPLUG = f"/api/v1/cplugs/{NAME}"


@pytest.fixture
def spawned(world, monkeypatch):  # noqa: F811
    started = []

    async def fake_spawn(self, spec):
        started.append(spec)
        self._state[spec.ctx.plugin_id] = "running"
        return "running"

    async def no_index() -> None:
        return None

    monkeypatch.setattr(Supervisor, "_spawn", fake_spawn)
    monkeypatch.setattr(world.rt.index, "ensure", no_index)
    assert owner_switch.write(world.state, True)
    world.rt.supervisor.set_safe_mode(False)
    world.rt.host = world.client.app.state.cplugs_host
    return started


def consent_body(w):
    sheet = w.client.get(f"{CPLUG}/sheet", headers=w.owner).json()
    ticks = [p["name"] for p in sheet["permissions"] if p["risk"] in ("medium", "high")]
    return {"digest": sheet["digest"], "body_sha": sheet["body_sha"], "grants_sha": sheet["grants_sha"], "ticks": ticks}


def row(w):
    return w.client.get(CPLUG, headers=w.owner).json()


def consented_then_edited(w):
    (w.src / "carnivore.json").write_text(json.dumps({"permissions": [{"name": "notify", "reason": "says the time"}]}))
    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).status_code == 200
    first = post(w).json()
    r = w.client.put(CPLUG, json={"revision": row(w)["revision"], "enabled": True, "grants": {"app": ["notify"]}, "consent": consent_body(w)},
                     headers=w.owner)
    assert r.status_code == 200 and r.json()["state"] == "active", r.text
    (w.src / "main.py").write_text("print('edited')\n")
    edited = post(w).json()
    assert edited["needs_approval"] is True
    assert row(w)["state"] == "needs_approval"
    return first["digest"], edited["digest"]


def test_grant_consent_only_after_resync_starts_the_new_code(world, spawned):
    w = world
    _old, new = consented_then_edited(w)
    spawned.clear()
    body = {"revision": row(w)["revision"], "grants": {"app": ["notify"]}, "consent": consent_body(w)}
    r = w.client.put(CPLUG, json=body, headers=w.owner)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "active" and r.json()["needs"] == [], r.json()
    assert owner_state.get(w.state, sidecar_registry.find(NAME).manifest).digest == new
    assert [s.code_digest for s in spawned] == [new] and not spawned[0].consent_owed
    assert w.rt.supervisor.state(NAME) == "running"


def test_enable_with_consent_after_resync_restarts_it(world, spawned):
    w = world
    _old, new = consented_then_edited(w)
    spawned.clear()
    body = {"revision": row(w)["revision"], "enabled": True, "grants": {"app": ["notify"]}, "consent": consent_body(w)}
    r = w.client.put(CPLUG, json=body, headers=w.owner)
    assert r.status_code == 200 and r.json()["state"] == "active", r.text
    assert [s.code_digest for s in spawned] == [new]


def test_restart_while_consent_owed_is_refused_and_starts_nothing(world, spawned):
    w = world
    consented_then_edited(w)
    spawned.clear()
    r = w.client.post(f"{CPLUG}/restart", headers=w.owner)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "needs_approval", r.text
    assert spawned == [] and w.rt.supervisor.state(NAME) != "running"
    assert row(w)["state"] == "needs_approval"


def test_boot_switch_first_call_and_crash_restart_refuse_owed_code(world, spawned):
    w = world
    consented_then_edited(w)
    spawned.clear()
    sup = w.rt.supervisor
    w.rt.loop.run_until_complete(w.rt.activate_enabled())
    assert sup.state(NAME) == "needs_approval" and spawned == []
    assert row(w)["state"] == "needs_approval"
    assert w.rt.loop.run_until_complete(sup.ensure(NAME)) is None and spawned == []

    owed = w.client.app.state.cplugs_host.sidecar_spec(sidecar_registry.find(NAME))
    assert owed.consent_owed is True
    sup._specs[NAME], sup._state[NAME] = owed, "backing_off"
    w.rt.loop.run_until_complete(sup._restart_after(NAME, 0.0))
    assert spawned == [] and sup.state(NAME) == "needs_approval"

    sup._state[NAME] = "backing_off"
    sup._specs[NAME] = replace(owed, consent_owed=False)
    w.rt.loop.run_until_complete(sup._restart_after(NAME, 0.0))
    assert len(spawned) == 1


def no_permission_plugin(w) -> None:
    manifest = json.loads((w.src / "cplug.json").read_text())
    (w.src / "cplug.json").write_text(json.dumps({**manifest, "permissions": {"app": []}, "routes": ["ping"]}))


def test_resync_of_a_consented_no_permission_plugin_answers_needs_approval_like_its_row(world, spawned):
    w = world
    no_permission_plugin(w)
    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).status_code == 200
    first = post(w).json()
    assert first["needs_approval"] is False
    r = w.client.put(CPLUG, json={"revision": row(w)["revision"], "enabled": True, "grants": {"app": []}, "consent": consent_body(w)},
                     headers=w.owner)
    assert r.status_code == 200 and r.json()["state"] == "active", r.text
    assert post(w).json()["needs_approval"] is False
    (w.src / "main.py").write_text("print('edited')\n")
    edited = post(w).json()
    assert row(w)["state"] == "needs_approval" and row(w)["needs"] == []
    assert edited["needs_approval"] is True


def test_a_route_of_a_plugin_waiting_for_approval_answers_needs_approval(world, spawned):
    w = world
    no_permission_plugin(w)
    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).status_code == 200
    post(w)
    r = w.client.put(CPLUG, json={"revision": row(w)["revision"], "enabled": True, "grants": {"app": []}, "consent": consent_body(w)},
                     headers=w.owner)
    assert r.status_code == 200, r.text
    (w.src / "main.py").write_text("print('edited')\n")
    post(w)
    spawned.clear()
    r = w.client.get(f"{CPLUG}/r/ping", headers=w.owner)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "needs_approval" and "approve" in r.json()["detail"]["detail"], r.text
    assert spawned == []
    assert owner_switch.write(w.state, False)
    r = w.client.get(f"{CPLUG}/r/ping", headers=w.owner)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cplug_disabled", r.text
