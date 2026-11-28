
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from src.api.auth import require_auth
from src.core.mcp import write_tools
from src.plugins.host import egress_log, gate, mcp as host_mcp
from tests.python.cplugs.renamed_world import World, build


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    built = build(tmp_path, monkeypatch)
    built.app.dependency_overrides[require_auth] = lambda: True
    return built


async def _revision(world: World, cplug_id: str) -> int:
    async with world.client() as client:
        return (await client.get(f"/api/v1/cplugs/{cplug_id}")).json()["revision"]


async def _put(world: World, cplug_id: str, **body: Any) -> Any:
    async with world.client() as client:
        return await client.put(f"/api/v1/cplugs/{cplug_id}", json={"revision": await _revision(world, "alpha"), **body})


@pytest.mark.asyncio
async def test_turning_the_old_id_off_with_a_dependent_on_asks_for_confirmation(world: World) -> None:
    await world.host().start()
    refused = await _put(world, "beta", enabled=False)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "has_dependents"
    assert refused.json()["detail"]["dependents"] == ["gamma"] and world.host().enabled("alpha")


@pytest.mark.asyncio
async def test_off_then_on_through_the_old_id_runs_stop_once_and_start_once(world: World) -> None:
    await world.host().start()
    assert world.hooks == ["start"]
    assert (await _put(world, "beta", enabled=False, confirm_dependents=True)).status_code == 200
    assert world.hooks == ["start", "stop"]
    assert (await _put(world, "beta", enabled=True)).status_code == 200
    assert world.hooks == ["start", "stop", "start"] and world.host()._started == {"alpha", "gamma"}


def test_a_context_for_the_old_id_is_refused(world: World) -> None:
    with pytest.raises(KeyError):
        world.host().context("beta")
    assert world.host().context("alpha", background=True) is not None


@pytest.mark.asyncio
async def test_the_old_id_on_the_egress_route_reads_the_renamed_plugin_rows(world: World) -> None:
    egress_log.EgressLog(world.state_dir).record("alpha", host="example.com", method="GET", permission="net", status=200,
                                                 bytes_out=1, bytes_in=1, ms=1, outcome="ok")
    async with world.client() as client:
        rows = (await client.get("/api/v1/cplugs/beta/egress")).json()["rows"]
    assert [r["host"] for r in rows] == ["example.com"]


@pytest.mark.asyncio
async def test_cplug_update_through_the_old_id_acts_on_the_renamed_plugin(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    await world.host().start()

    async def approved(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return await args[7](True)

    monkeypatch.setattr(write_tools, "park", approved)
    manager = SimpleNamespace(app=world.app)
    args = {"cplug_id": "beta", "revision": await _revision(world, "alpha"), "enabled": False, "confirm_dependents": True}
    await host_mcp.cplug_update(manager, SimpleNamespace(), args)
    assert world.hooks == ["start", "stop"] and not world.host().enabled("alpha")


def test_the_gate_answers_the_old_id_for_the_renamed_plugin(world: World) -> None:
    assert gate.is_on("beta", world.state_dir) and gate.blocked_by("beta", world.state_dir) == ()
    assert gate.blocked_by("gamma", world.state_dir) == ()
