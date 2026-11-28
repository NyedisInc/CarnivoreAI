
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from src.api.auth import require_auth
from src.core.plugin_health import gather
from src.plugins.host import identity, install_gates, renamed, runtime, sideload_routes
from src.plugins.host import state as owner_state
from src.plugins.sdk import manifest as m
from tests.python.cplugs.renamed_world import OWNED_FILE, World, build, raw_manifest


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    built = build(tmp_path, monkeypatch)
    built.app.dependency_overrides[require_auth] = lambda: True
    old = tmp_path / owner_state.STATE_DIR_NAME / "beta"
    (old / "files").mkdir(parents=True)
    (old / "files" / "a.png").write_bytes(b"png")
    owner_state.update(tmp_path, m.parse_manifest(raw_manifest("beta")), None, lambda st: st)
    return built


async def _purge(world: World, cplug_id: str) -> Any:
    async with world.client() as client:
        return await client.post(f"/api/v1/cplugs/{cplug_id}/purge", json={"dry_run": True})


@pytest.mark.asyncio
async def test_the_old_folder_is_not_listed_as_a_removed_plugin(world: World) -> None:
    async with world.client() as client:
        rows = (await client.get("/api/v1/cplugs")).json()
    ids = [r["id"] for r in (rows["cplugs"] if isinstance(rows, dict) else rows)]
    assert "alpha" in ids and "beta" not in ids


@pytest.mark.asyncio
@pytest.mark.parametrize("on", [True, False])
async def test_a_purge_of_the_old_id_is_refused_while_the_renamed_plugin_is_on_or_off(world: World, on: bool) -> None:
    owned = world.state_dir / OWNED_FILE
    owned.write_text("alpha's own data")
    if not on:
        async with world.client() as client:
            rev = (await client.get("/api/v1/cplugs/alpha")).json()["revision"]
            off = await client.put("/api/v1/cplugs/alpha", json={"revision": rev, "enabled": False, "confirm_dependents": True})
        assert off.status_code == 200
    refused = await _purge(world, "beta")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "cplug_renamed" and refused.json()["detail"]["renamed_to"] == "alpha"
    assert (world.state_dir / owner_state.STATE_DIR_NAME / "beta" / "files" / "a.png").exists()
    assert "beta" in owner_state.stored_ids(world.state_dir)
    assert "before_purge" not in world.hooks and owned.read_text() == "alpha's own data"


def test_the_health_report_counts_the_old_folder_and_entry_as_owned(world: World) -> None:
    report = gather.build_report(world.host())
    assert "beta" not in [o.key for o in report.orphan_data]
    assert "beta" not in report.stale_state


def test_the_owner_publisher_may_not_take_an_old_id(world: World) -> None:
    shipped, old = runtime.reserved_plugin_ids(), runtime.renamed_ids()
    assert old == frozenset({"beta"})
    with pytest.raises(identity.InstallRefused, match="reserved"):
        identity.register_install(world.state_dir, "beta", "carnivore/beta", shipped, renamed_ids=old)
    problem = install_gates.name_problem(world.state_dir, "beta", "carnivore/beta", shipped, renamed_ids=old)
    assert problem is not None and problem.code == "name_reserved"
    assert install_gates.name_problem(world.state_dir, "alpha", "carnivore/alpha", shipped, renamed_ids=old) is None


def test_a_boot_alerts_when_an_install_already_holds_an_old_id(world: World) -> None:
    identity.register_install(world.state_dir, "beta", "carnivore/beta", frozenset())
    raised: List[Dict[str, Any]] = []
    held = renamed.alert_shadowed_installs(world.state_dir, runtime.definitions(),
                                           lambda key, **kw: raised.append({"key": key, **kw}))
    assert held == ["beta"]
    assert [r["key"] for r in raised] == ["cplug_rename.held.beta"] and raised[0]["params"] == {"name": "beta", "plugin": "alpha"}
    assert renamed.alert_shadowed_installs(world.state_dir, (), raised.append) == [] and len(raised) == 1


def test_both_install_doors_refuse_the_old_id_from_their_own_list(world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.api import catalog_cplug_gates  # noqa: PLC0415

    assert {"alpha", "beta", "gamma"} <= runtime.reserved_plugin_ids() == catalog_cplug_gates._shipped_ids()
    monkeypatch.setattr(identity, "RETIRED_IDS", frozenset())
    problem = install_gates.name_problem(world.state_dir, "beta", "acme/beta", catalog_cplug_gates._shipped_ids())
    assert problem is not None and problem.code == "name_reserved"
    source = tmp_path / "src-beta"
    source.mkdir()
    (source / "carnivore.toml").write_text(
        'schema = 2\n'
        'id = "beta"\n'
        'name = "Beta"\n'
        'description = "A test."\n'
        'version = "1.0.0"\n'
        'kind = "plugin"\n'
        'author = "Tester"\n\n'
        '[run]\n'
        'cmd = ["python3", "main.py"]\n\n'
        '[permissions]\n'
        'write = ["notify"]\n',
        encoding="utf-8",
    )
    (source / "main.py").write_text("print('tick')\n")
    with pytest.raises(HTTPException) as refused:
        sideload_routes._sync_blocking(world.state_dir, source, None)
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "name_reserved"
