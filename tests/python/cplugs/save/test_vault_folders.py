
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime
from src.cplugs.save.vault import folders, health, retention
from src.cplugs.save.vault.follow import Engine
from src.cplugs.sdk import vault_sources
from tests.python.cplugs.save.vault_helpers import World, store_plugin_entry, store_save_settings

UNIT = "reviewboard.boards"


def _checkout(root: Path) -> None:
    (root / "board-1").mkdir(parents=True)
    (root / "board-1" / "board.json").write_text('{"title": "one", "round": 1}')
    (root / "board-1" / "shot.png").write_bytes(os.urandom(400_000))
    (root / "board-2").mkdir()
    (root / "board-2" / "board.json").write_text('{"title": "two"}')
    (root / ".git" / "objects" / "ab").mkdir(parents=True)
    (root / ".git" / "objects" / "ab" / "cdef01").write_bytes(os.urandom(2000))
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "index.lock").write_text("held")
    (root / "board-2" / "__pycache__").mkdir()
    (root / "board-2" / "__pycache__" / "x.pyc").write_bytes(b"cache")


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_marked_folder_is_backed_up_changed_and_the_old_version_is_restorable(tmp_path: Path) -> None:
    world, boards = World(tmp_path), tmp_path / "review-boards" / "boards"
    _checkout(boards)
    original = {k: v for k, v in _tree(boards).items() if not k.endswith(".lock") and "__pycache__" not in k}
    first = world.vault.capture_folder(UNIT, boards)
    assert first.status == "written"
    rels = {f.rel for f in world.vault.manifests.read(UNIT, first.point_id).files}
    assert ".git/objects/ab/cdef01" in rels and ".git/HEAD" in rels
    assert ".git/index.lock" not in rels and not any("__pycache__" in r for r in rels)
    (boards / "board-1" / "board.json").write_text('{"title": "one", "round": 2}')
    (boards / "board-3").mkdir()
    (boards / "board-3" / "board.json").write_text('{"title": "three"}')
    second = world.vault.capture_folder(UNIT, boards)
    assert second.status == "written" and second.point_id != first.point_id
    assert second.new_chunks <= 3, "the unchanged 400 KB attachment and git object must dedupe, not be stored again"
    assert world.vault.capture_folder(UNIT, boards).status == "unchanged"
    live = _tree(boards)
    target, result, used = folders.restore_folder(world.vault, UNIT, first.point_id)
    assert used == first.point_id and target.parent == boards.parent and target.name.startswith("boards.restored-")
    assert _tree(target) == original and len(result.written) == len(original)
    assert _tree(boards) == live
    again, _result, _used = folders.restore_folder(world.vault, UNIT, first.point_id)
    assert again != target and again.name.endswith("-2")


def test_a_deleted_file_leaves_the_point_that_holds_it_kept(tmp_path: Path) -> None:
    world, boards = World(tmp_path), tmp_path / "boards"
    _checkout(boards)
    first = world.vault.capture_folder(UNIT, boards)
    (boards / "board-2" / "board.json").unlink()
    second = world.vault.capture_folder(UNIT, boards)
    assert second.status == "written"
    assert "board-2/board.json" not in {f.rel for f in world.vault.manifests.read(UNIT, second.point_id).files}
    assert world.vault.manifests.is_kept(UNIT, first.point_id)
    for i in range(15):
        (boards / "board-1" / "board.json").write_text(f'{{"round": {i}}}')
        world.vault.capture_folder(UNIT, boards)
    retention.thin_unit(world.vault, UNIT, max_points=3)
    assert first.point_id in world.vault.manifests.point_ids(UNIT)


def test_a_folder_that_overlaps_the_vault_is_refused(tmp_path: Path) -> None:
    world = World(tmp_path)
    outcome = world.vault.capture_folder("someplugin.state", world.state)
    assert outcome.status == "failed" and not world.vault.manifests.point_ids("someplugin.state")


def _engine(world: World) -> Engine:
    return Engine(lambda: world.vault, world.state, lambda: world.sources, side_dbs=lambda: [],
                  folders=lambda: vault_sources.vault_folders(world.state))


def test_the_engine_backs_up_marked_folders_only_and_the_health_lists_them(tmp_path: Path) -> None:
    world, boards = World(tmp_path), tmp_path / "review-boards" / "boards"
    _checkout(boards)
    plugin_dir = world.state / "cplugs" / "reviewboard"
    (plugin_dir / "drafts").mkdir(parents=True)
    (plugin_dir / "drafts" / "board-1.json").write_text('{"ticks": [1]}')
    (plugin_dir / "locks").mkdir()
    (plugin_dir / "locks" / "board-1.lock").write_text("x")
    store_plugin_entry(world.state, "reviewboard", {"boardsRoot": str(boards)}, enabled=False)
    _engine(world).run_slice()
    assert not [u for u in world.vault.manifests.units() if u.startswith("reviewboard.")], "an off plugin's folders are not captured"
    store_plugin_entry(world.state, "reviewboard", {"boardsRoot": str(boards)}, enabled=True)
    _engine(world).run_slice()
    units = {u for u in world.vault.manifests.units() if u.startswith("reviewboard.")}
    assert units == {"reviewboard.boards", "reviewboard.drafts"}
    rows = {r["unit"]: r for r in health.evaluate(health.read(world.state))["folders"]}
    assert set(rows) == units and rows[UNIT]["status"] == "written" and rows[UNIT]["root"] == str(boards)
    assert rows[UNIT]["bytes"] > 400_000 and rows[UNIT]["files"] == 5 and rows[UNIT]["points"] == 1


def test_a_reviewboard_purge_keeps_the_vault_copies(tmp_path: Path, monkeypatch) -> None:
    world, boards = World(tmp_path), tmp_path / "review-boards" / "boards"
    _checkout(boards)
    drafts = world.state / "cplugs" / "reviewboard" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "board-1.json").write_text('{"ticks": [1, 2]}')
    before = _tree(drafts)
    store_plugin_entry(world.state, "reviewboard", {"boardsRoot": str(boards)}, enabled=True)
    _engine(world).run_slice()
    store_plugin_entry(world.state, "reviewboard", {"boardsRoot": str(boards)}, enabled=False)
    app = FastAPI()
    host = runtime.install(app, world.state)
    host.publish = lambda *_a, **_k: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    try:
        with TestClient(app) as client:
            price = client.post("/api/v1/cplugs/reviewboard/purge", json={"dry_run": True}).json()
            done = client.post("/api/v1/cplugs/reviewboard/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
            assert done.status_code == 200, done.text
    finally:
        asyncio.run(host.stop())
    assert not drafts.exists() and (boards / "board-1" / "board.json").exists()
    retention.assess(world.vault)
    retention.collect_garbage(world.vault, grace=0)
    assert retention.protection(world.vault, "reviewboard.drafts", world.vault.manifests.newest("reviewboard.drafts")) == "original_gone"
    target, _result, _used = folders.restore_folder(world.vault, "reviewboard.drafts")
    assert _tree(target) == before and target.parent == drafts.parent


def test_the_backup_menu_switch_stops_new_points_for_one_folder_and_keeps_the_old_ones(tmp_path: Path, monkeypatch) -> None:
    from src.cplugs.save import folder_routes
    from src.cplugs.save.service import RUNTIME
    from src.cplugs.sdk import transcript_files

    world, boards = World(tmp_path), tmp_path / "review-boards" / "boards"
    _checkout(boards)
    drafts = world.state / "cplugs" / "reviewboard" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "board-1.json").write_text('{"ticks": [1]}')
    store_plugin_entry(world.state, "reviewboard", {"boardsRoot": str(boards)}, enabled=True)
    _engine(world).run_slice()
    held = world.vault.manifests.point_ids(UNIT)
    assert len(held) == 1 and world.vault.manifests.point_ids("reviewboard.drafts")
    store_save_settings(world.state, {"vaultFolderOptOut": f"{UNIT}, gone.plugin"})
    (boards / "board-1" / "board.json").write_text('{"title": "one", "round": 9}')
    (drafts / "board-1.json").write_text('{"ticks": [1, 2]}')
    _engine(world).run_slice()
    assert world.vault.manifests.point_ids(UNIT) == held, "a switched-off folder takes no new point; the old one stays"
    assert len(world.vault.manifests.point_ids("reviewboard.drafts")) == 2, "a folder that is not switched off is still backed up"
    rows = {r["unit"]: r for r in health.evaluate(health.read(world.state))["folders"]}
    assert rows[UNIT]["status"] == "switched_off" and rows[UNIT]["points"] == 1
    monkeypatch.setattr(RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(transcript_files, "state_dir", lambda: world.state)
    listed = {f.unit: f for f in folder_routes.list_now().folders}
    assert listed[UNIT].marked and not listed[UNIT].backup_on and listed["reviewboard.drafts"].backup_on
    store_save_settings(world.state, {"vaultFolderOptOut": ""})
    _engine(world).run_slice()
    assert len(world.vault.manifests.point_ids(UNIT)) == 2, "switched back on, the next pass takes the point"
