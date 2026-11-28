
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from src.api.auth import require_auth
from src.core.core_owned_files import registry
from src.plugins.host import renamed_files
from src.plugins.host import state as owner_state
from tests.python.cplugs.renamed_world import World, build

ATTACHED = ("files/7/ab12cd34-a.png", "files/7/cd34ab12-b.txt", "files/9/ef56ab78-c.pdf")


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    built = build(tmp_path, monkeypatch)
    built.app.dependency_overrides[require_auth] = lambda: True
    old = tmp_path / owner_state.STATE_DIR_NAME / "beta"
    for rel in ATTACHED:
        (old / rel).parent.mkdir(parents=True, exist_ok=True)
        (old / rel).write_bytes(rel.encode())
    (old / "huddle.db").write_bytes(b"core db")
    monkeypatch.setattr(registry, "CORE_OWNED", MappingProxyType({**registry.CORE_OWNED, "beta": ("huddle.db",)}))
    outcome = renamed_files.migrate(tmp_path, {"beta": "alpha"}, free_space=lambda _s: 0, alert=lambda *a, **k: None)
    assert outcome.state == {"beta": "no_space"}
    return built


def old_files(world: World) -> list:
    old = world.state_dir / owner_state.STATE_DIR_NAME / "beta"
    return sorted(p.relative_to(old).as_posix() for p in (old / "files").rglob("*") if p.is_file())


@pytest.mark.asyncio
async def test_real_attachments_in_the_old_folder_are_not_a_removed_plugin_and_cannot_be_purged(world: World) -> None:
    async with world.client() as client:
        rows = (await client.get("/api/v1/cplugs")).json()
        ids = [r["id"] for r in (rows["cplugs"] if isinstance(rows, dict) else rows)]
        priced = await client.post("/api/v1/cplugs/beta/purge", json={"dry_run": True})
        real = await client.post("/api/v1/cplugs/beta/purge", json={"dry_run": False, "confirm_token": "x"})
    assert "beta" not in ids
    assert priced.status_code == real.status_code == 409 and real.json()["detail"]["code"] == "cplug_renamed"
    assert old_files(world) == sorted(ATTACHED)


def test_the_host_binds_the_old_folder_on_the_renamed_plugins_storage(world: World) -> None:
    storage = world.host().storage("alpha")
    assert storage.previous_path == world.state_dir / owner_state.STATE_DIR_NAME / "beta"
    assert world.host().storage("gamma").previous_path is None


@pytest.mark.asyncio
async def test_a_purge_of_the_renamed_plugin_keeps_core_files_in_the_old_folder(world: World) -> None:
    async with world.client() as client:
        rev = (await client.get("/api/v1/cplugs/alpha")).json()["revision"]
        off = await client.put("/api/v1/cplugs/alpha", json={"revision": rev, "enabled": False, "confirm_dependents": True})
        assert off.status_code == 200
        price = (await client.post("/api/v1/cplugs/alpha/purge", json={"dry_run": True})).json()
        assert price["files"] >= len(ATTACHED) and price["kept"] >= 1
        done = await client.post("/api/v1/cplugs/alpha/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
    assert done.status_code == 200
    assert old_files(world) == []
    assert (world.state_dir / owner_state.STATE_DIR_NAME / "beta" / "huddle.db").read_bytes() == b"core db"
