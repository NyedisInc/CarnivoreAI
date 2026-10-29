
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import List

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.api import catalog_installed_routes as routes
from src.api.auth import require_auth
from src.core.catalog.index_refresher import HOURLY_SECONDS, IndexRefresher
from src.core.skills import install_by_reference
from src.cplugs.host import identity, owner_switch, routes as host_routes, runtime, sidecar_boot, sidecar_index
from tests.python.cplugs.test_cplug_update_revoke import (AVAILABLE, ITEM, KEY_ID, NAME, FakeCache, FakeClock, alive, lay_code)

sandboxed = pytest.mark.skipif(not AVAILABLE, reason="needs macOS sandbox-exec and the framework Python")


@sandboxed
def test_apply_version_stops_before_the_swap_strips_after_and_restarts_on_a_failed_swap(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    lay_code(state, "1.0.0", "tick")
    identity.register_install(state, NAME, ITEM, {d.id for d in runtime.definitions()})
    rows = [SimpleNamespace(item_id=ITEM, kind="cplug", source_index_url="https://index.example/v1", publisher_key_id=KEY_ID)]
    owner_switch.write(state, True)
    swaps: List[str] = []

    def fake_swap(request, **_):
        swaps.append("swap")
        if len(swaps) == 1:
            raise HTTPException(409, "stale")
        lay_code(state, "2.0.0", "tock")
        return SimpleNamespace(item_id=ITEM, version="2.0.0")

    async def fake_stage(*_a, **_k):
        return tmp_path, SimpleNamespace(path=tmp_path, digest="d")

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(routes, "carries_scripts", lambda v: False)
    monkeypatch.setattr(routes, "fetch_and_stage", fake_stage)
    monkeypatch.setattr(routes, "check_digest", lambda *_: None)
    monkeypatch.setattr(routes, "hash_file", lambda *_: ("sha", 0))
    monkeypatch.setattr(routes, "staged_plugin_declares_code", lambda *_: False)
    monkeypatch.setattr(routes, "consent_carried", lambda *_a, **_k: True)
    monkeypatch.setattr(routes, "discard_staging", lambda *_: None)
    monkeypatch.setattr(routes, "apply_update_now", fake_swap)
    monkeypatch.setattr(routes.install_reporter, "schedule_for", lambda *_: None)
    monkeypatch.setattr(routes, "installed_view", lambda *_: {"ok": True})
    monkeypatch.setattr(routes, "annotate_watch", lambda *_a, **_k: None)

    async def go() -> None:
        app = FastAPI()
        host = runtime.install(app, state)
        host.publish = lambda *_: None
        rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False, app_version="9.9.9",
                                         raise_alert=lambda *_a, **_k: None, resolve_alert=lambda *_: None)
        rt._ledger_rows = lambda: rows
        rt.index = sidecar_index.IndexAdapter(rt, FakeCache())
        app.state.sidecar_runtime = rt
        app.state.services = SimpleNamespace(settings_reader=SimpleNamespace(state_dir=lambda: state))
        rt.load_registry()
        app.include_router(host_routes.router, prefix="/api/v1")
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        await rt._apply()
        request = SimpleNamespace(app=app)
        base = f"/api/v1/cplugs/{NAME}"
        row = SimpleNamespace(item_id=ITEM, kind="cplug")
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
                assert rt.index.third_party_enabled() is False
                sheet = (await http.get(f"{base}/sheet")).json()
                names = [p["name"] for p in sheet["permissions"]]
                rev = (await http.get(base)).json()["revision"]
                consent = {"digest": sheet["digest"], "body_sha": sheet["body_sha"], "grants_sha": sheet["grants_sha"], "ticks": names}
                done = await http.put(base, json={"revision": rev, "enabled": True, "grants": {"app": names}, "consent": consent})
                assert done.status_code == 200 and done.json()["process"] == "idle"
                await rt.supervisor.ensure(NAME)
                assert rt.index.third_party_enabled() is True
                owner_switch.write(state, False)
                assert rt.index.third_party_enabled() is False
                owner_switch.write(state, True)

                first = rt.supervisor.process(NAME)
                with pytest.raises(HTTPException) as err:
                    await routes.apply_version(request, row, None, SimpleNamespace(v="2.0.0", digest="d"),
                                               SimpleNamespace(consent=None, expected_revision=1), None)
                assert err.value.status_code == 409 and swaps == ["swap"]
                back = rt.supervisor.process(NAME)
                assert back is not None and alive(back.pid) and not alive(first.pid)
                assert (await http.get(base)).json()["version"] == "1.0.0"

                running = rt.supervisor.process(NAME)
                await routes.apply_version(request, row, None, SimpleNamespace(v="2.0.0", digest="d"),
                                           SimpleNamespace(consent=None, expected_revision=1), None)
                assert not alive(running.pid) and rt.supervisor.process(NAME) is None
                after = (await http.get(base)).json()
                assert after["version"] == "2.0.0" and after["state"] == "needs_approval" and after["grants"]["app"] == []
                assert rt.supervisor.state(NAME) == "disabled" and not rt.supervisor._safe_mode
        finally:
            await rt.supervisor.shutdown() if hasattr(rt.supervisor, "shutdown") else None

    asyncio.run(go())


def test_the_refresher_asks_hourly_while_every_hour_not_once_per_pass():
    slept: List[float] = []
    on = {"v": False}
    arm = [True]

    async def sleep(s: float) -> None:
        slept.append(s)
        if arm[0]:
            on["v"] = True

    r = IndexRefresher(SimpleNamespace(), sleep=sleep)
    r.hourly_while = lambda: on["v"]
    asyncio.run(r._sleep_until_due())
    assert slept == [HOURLY_SECONDS]
    slept.clear()
    arm[0] = False
    on["v"] = False
    asyncio.run(r._sleep_until_due())
    assert len(slept) > 1 and sum(slept) > 5 * HOURLY_SECONDS and all(s <= HOURLY_SECONDS for s in slept)


def test_a_cplug_is_refused_by_reference_as_cplug_by_hand(monkeypatch):
    item = SimpleNamespace(kind="cplug", versions=[])
    snapshot = SimpleNamespace(verified=object())
    cache = SimpleNamespace(snapshot=lambda: snapshot)
    services = SimpleNamespace(catalog=SimpleNamespace(index_cache=cache))
    monkeypatch.setattr("src.api.catalog_views.find_item", lambda snap, item_id: (item, False))
    ref = install_by_reference.Ref(item_id=ITEM, kind="cplug", version="1.0.0", digest="d", body_sha="b")
    got = asyncio.run(install_by_reference._gates(services, ref))
    assert got == (None, None, "cplug_by_hand")
    item.kind = "skill"
    item.versions = []
    monkeypatch.setattr("src.api.catalog_views.find_item", lambda snap, item_id: (item, False))

    async def get():
        return snapshot

    cache.get = get
    assert asyncio.run(install_by_reference._gates(services, install_by_reference.Ref(ITEM, "skill", "1.0.0", "d", "b")))[2] != "cplug_by_hand"
