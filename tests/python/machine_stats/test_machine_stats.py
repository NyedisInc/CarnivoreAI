
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.machine_stats_routes import router
from src.core.machine_stats import MachineStatsWatch
from src.core.machine_stats import watch as watch_module
from src.core.resource_push.topics import MACHINE_STATS, RESOURCE_TOPICS


class FakeSampler:

    def __init__(self, cpus):
        self.cpus = list(cpus)
        self.reads = 0

    def read(self, max_age=2.0):
        self.reads += 1
        cpu = self.cpus[min(self.reads - 1, len(self.cpus) - 1)]
        return {"cpu_percent": cpu, "memory_percent": 40.0, "disk_percent": 50.0, "load_1": 1.0}


def test_route_is_numbers_only_authenticated_and_leases(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as http:
        assert http.get("/api/v1/machine-stats").status_code in (401, 403)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as http:
        body = http.get("/api/v1/machine-stats").json()
        assert app.state.machine_stats_watch.running
    assert MACHINE_STATS in RESOURCE_TOPICS
    assert body["disk_free_bytes"] and body["disk_total_bytes"] and body["cpu_count"]
    assert not {"hostname", "path", "user", "serial", "ip"} & set(body)


@pytest.mark.asyncio
async def test_sampler_is_viewer_gated_and_announces_changes() -> None:
    now = [0.0]
    named: list[str] = []

    async def sleep(seconds: float) -> None:
        now[0] += seconds
        await asyncio.sleep(0)

    sampler = FakeSampler([10.0, 10.5, 40.0, 40.0, 40.0, 40.0, 40.0])
    watch = MachineStatsWatch(sampler, notify=named.append, sleep=sleep, clock=lambda: now[0])
    await asyncio.sleep(0.01)
    assert sampler.reads == 0 and not watch.running
    watch.touch()
    await watch._task
    assert named[0] == MACHINE_STATS and sampler.reads >= 3
    assert len(named) >= 2
    assert not watch.running
    assert now[0] <= watch_module.LEASE_SECONDS + watch_module.TICK_SECONDS
