
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from src.api import catalog_routes
from src.api.auth import require_auth
from src.core.catalog.index_refresher import IndexRefresher
from src.cplugs.runtime.supervisor import Supervisor
from src.cplugs.host.sidecar_index import IndexAdapter
from tests.python.cplugs.runtime.test_cplug_lazy import PID, FakeProc, spec, world  # noqa: F401


def catalog_spec():
    base = spec()
    return replace(base, version="1.0.0", code_digest="d" * 64, ctx=replace(base.ctx, tier="catalog"))


class FakeCache:

    def __init__(self) -> None:
        self.versions: frozenset = frozenset()
        self.refused = None
        self.fetched = True

    def snapshot(self) -> SimpleNamespace:
        verified = SimpleNamespace(generated_at=datetime.now(timezone.utc), serial=1, expires_at=None)
        return SimpleNamespace(verified=verified, refusal=self.refused, degraded=False, stale=False, fetched_at=None)

    async def refresh_now(self):
        return self.snapshot(), self.fetched

    def revoked_sets(self, verified):
        return frozenset(), self.versions


def _run(world, monkeypatch, revoke: bool, refused=None, fetched: bool = True):
    monkeypatch.setattr(Supervisor, "_code_intact", staticmethod(lambda spec: True))
    async def go():
        cache = FakeCache()
        cache.refused = refused
        cache.fetched = fetched
        runtime = SimpleNamespace(supervisor=world.sup, _ledger_rows=lambda: [])
        refresher = IndexRefresher(cache)
        refresher.after_pass = IndexAdapter(runtime, cache).sync
        app = FastAPI()
        app.include_router(catalog_routes.router)
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        app.state.services = SimpleNamespace(catalog=SimpleNamespace(index_cache=cache))
        app.state.catalog_index_refresher = refresher
        await world.sup.set_index({"expires_at": "2999-01-01T00:00:00Z"})
        await world.sup.activate(catalog_spec())
        proc = await world.sup.ensure(PID)
        assert world.sup.state(PID) == "running" and proc.ended is None
        if revoke:
            cache.versions = frozenset({f"{PID}@1.0.0"})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
            assert (await http.post("/catalog/index/refresh")).status_code == 200
        return world.sup.state(PID), proc.ended

    return asyncio.run(go())


def test_a_forced_refresh_stops_a_sidecar_the_new_index_revokes(world, monkeypatch):
    state, ended = _run(world, monkeypatch, revoke=True)
    assert state == "revoked" and ended is not None


def test_a_forced_refresh_with_no_revocation_stops_nothing(world, monkeypatch):
    state, ended = _run(world, monkeypatch, revoke=False)
    assert state == "running" and ended is None


def test_a_press_inside_the_force_floor_still_stops_a_revoked_sidecar(world, monkeypatch):
    state, ended = _run(world, monkeypatch, revoke=True, fetched=False)
    assert state == "revoked" and ended is not None
