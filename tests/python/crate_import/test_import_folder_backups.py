
from __future__ import annotations

import dataclasses
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from src.core.crate_import import apply as ap
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.deepsearch import fallback_hook as fb
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.registry import CPLUGS
from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import task_folders
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.cplugs.crate.test_plugin_data import OWN_ONLY_KEPT, manifest_with, marker
from tests.python.cplugs.reviewboard.boards import make_board, make_root
from tests.python.crate_import.test_import_boards import PLUGIN, SLUG_MINE, SLUG_NESTED, board_raw, new_item_of, relinker
from tests.python.crate_import.test_import_same_path import run
from tests.python.crate_import.test_import_undo_post_commit import RecordingHooks
from tests.python.crate_import.test_import_work_side import target_install

UNIT = f"{PLUGIN}.boards"
BOARDS = {"id": "boards", "kind": "folder", "root_setting": "boardsRoot", "scope_by": "task_item_id", "policy": {**OWN_ONLY_KEPT, "backup": "vault"}}


def make_vault(root: Path) -> Vault:
    root.mkdir(parents=True, exist_ok=True)
    (root / "VAULT.json").write_text('{"format": 1}')
    return Vault(root)


def export_rig(tmp: Path) -> SimpleNamespace:
    (tmp / "w").mkdir()
    w = make_world(tmp / "w")
    with closing(sqlite3.connect(w.main)) as conn:
        conn.execute("UPDATE work_items SET text = 'item ' || id, created_at = 100.0 + id")
        conn.commit()
    (tmp / "srcb").mkdir()
    root = make_root(tmp / "srcb")
    make_board(root, board_raw(SLUG_MINE, w.item_p))
    nested = root / f"proj-{w.p1}"
    marker(nested, ".tm-project", {"list": str(w.p1)})
    marker(nested / f"task-{w.item_b}", ".tm-task", {"item_id": w.item_b})
    (nested / f"task-{w.item_b}" / "boards").mkdir()
    make_board(nested / f"task-{w.item_b}" / "boards", board_raw(SLUG_NESTED, None))
    vault = make_vault(tmp / "source-vault")
    assert vault.capture_folder(UNIT, root).status == "written"
    (root / SLUG_MINE / "r001.html").write_text("<p>second round</p>")
    assert vault.capture_folder(UNIT, root).status == "written"
    save = next(d.manifest for d in CPLUGS if d.id == "save")
    w.locations = replace(w.locations, plugin_manifests=(manifest_with([BOARDS]), save), plugin_enabled={PLUGIN: True, "save": True},
                          plugin_settings={PLUGIN: {"boardsRoot": str(root)}})
    fb.register("folder-import-source", BackupTranscripts(vault=lambda: vault))
    try:
        env = env_for(w)
        plan = build_export_plan(env, project_request(w, backup_units=(UNIT,)))
        assert plan.ok, plan.blockers
        result = run_export(env, plan, JobHandle("fi"))
    finally:
        fb.unregister("folder-import-source")
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=w, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id, vault=vault)


def wired(tmp: Path, crate: SimpleNamespace, *, save_on: bool = True, own: bool = True, **kw: Any):
    from src.core.crate_import.env import StoreHome
    from src.core.db import connect, db_path_for
    from src.core.exports.store import crate_written_key

    install = target_install(tmp, crate, **kw)
    if not own:
        with closing(connect(db_path_for(install.state), create=False)) as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", (crate_written_key(crate.bundle_id),))
            conn.commit()
    root = make_root(tmp / "t")
    vault = make_vault(tmp / "target-vault")
    sources: List[Any] = [BackupTranscripts(vault=lambda: vault)] if save_on else []
    env = replace(install.env, plugin_homes=lambda plugin, data: StoreHome(root, "kept") if (plugin, data) == (PLUGIN, "boards") else None,
                  relink_board=relinker(root, []), backup_sources=lambda: sources)
    return replace(install, env=env), root, vault


def foreign_request(install: Any) -> ImportRequest:
    return ImportRequest(mode="relocate", new_root=str(Path(install.projects) / "moved"), include_plugin_data=True)


def points_of(vault: Vault) -> Dict[str, Any]:
    return {m.point_id: m for m in vault.manifests.points(UNIT)}


def test_the_points_are_filed_where_the_boards_were_restored(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, root, vault = wired(tmp_path, crate)
    receipt = run(crate, install)
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    block = receipt.backups["folders"]
    assert block["adopted"] == 2 and block["refused"] == [] and block["board_not_placed"] == {}
    w = crate.world
    new_p, new_b = new_item_of(install, w.item_p), new_item_of(install, w.item_b)
    assert new_p != w.item_p
    expected = {SLUG_MINE: task_folders.find_task(root, new_p).relative_to(root).as_posix() + f"/boards/{SLUG_MINE}",
                SLUG_NESTED: task_folders.find_task(root, new_b).relative_to(root).as_posix() + f"/boards/{SLUG_NESTED}"}
    held = points_of(vault)
    assert len(held) == 2
    for manifest in held.values():
        assert manifest.kind == "folder" and manifest.family == "plugin" and manifest.working_dir == str(root)
        rels = {f.rel for f in manifest.files}
        assert rels and all(any(r.startswith(prefix + "/") for prefix in expected.values()) for r in rels), rels
        assert not [r for r in rels if r.startswith(f"proj-{w.p1}/") or r.startswith(SLUG_MINE)], "the source's layout is not carried over"
        assert vault.manifests.is_kept(UNIT, manifest.point_id)
        for entry in manifest.files:
            assert len(b"".join(vault.blobs.get(c) for c in entry.chunks)) == entry.length
    from src.cplugs.save.vault import folders

    target, _result, _used = folders.restore_folder(vault, UNIT)
    assert (target / expected[SLUG_MINE] / "sidecar.json").is_file()
    assert run(crate, install).backups["folders"]["adopted"] == 0 and len(points_of(vault)) == 2
    with cf.open_crate(crate.path) as reader:
        again = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
    assert [r["status"] for r in again["backups"]["folders"]] == ["present"]


def test_a_foreign_crate_files_only_the_ticked_families(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, root, vault = wired(tmp_path, crate, own=False)
    request = foreign_request(install)
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
    assert plan["ok"], plan["blockers"]
    row = plan["backups"]["folders"][0]
    assert plan["provenance"] == "foreign" and (row["unit"], row["status"], row["reason"]) == (UNIT, "not_restored", "backups_not_chosen")
    assert {"what": f"backups:{UNIT}", "why": "backups_not_chosen"} in plan["not_restored"]
    assert run(crate, install, request=request).backups["folders"]["adopted"] == 0 and vault.manifests.units() == []
    (tmp_path / "ticked").mkdir()
    ticked, _root, filed = wired(tmp_path / "ticked", crate, own=False)
    receipt = run(crate, ticked, request=replace(foreign_request(ticked), file_backup_units=(UNIT,)))
    assert receipt.backups["folders"]["adopted"] == 2 and len(points_of(filed)) == 2
    (tmp_path / "off").mkdir()
    off_install, _r, _v = wired(tmp_path / "off", crate, save_on=False, own=False)
    with cf.open_crate(crate.path) as reader:
        off = build_plan(reader, off_install.env, replace(foreign_request(off_install), file_backup_units=(UNIT,)), crate_sha256=crate.sha256,
                         encrypted=False)
    assert off["backups"]["folders"][0]["reason"] == "backup_plugin_off" and off["backups"]["provider_enabled"] is False


def test_an_undo_removes_exactly_the_filed_points(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, root, vault = wired(tmp_path, crate)
    own = vault.capture_folder(UNIT, root)
    assert own.status in ("written", "no_files")
    before = set(points_of(vault))
    hooks, import_id = RecordingHooks(), new_import_id()
    receipt = run(crate, install, hooks=hooks, import_id=import_id)
    assert receipt.backups["folders"]["adopted"] == 2
    assert len(set(points_of(vault)) - before) == 2
    fb.register("folder-import-target", BackupTranscripts(vault=lambda: vault))
    try:
        report = ap.recover_files(hooks.log, install.env, import_id)
    finally:
        fb.unregister("folder-import-target")
    assert not report.errors, report
    assert set(points_of(vault)) == before, "the undo removed the filed points and nothing else"


def wired_default(tmp: Path, crate: SimpleNamespace):
    from src.cplugs.sdk.crate_import import plugin_homes_of

    install = target_install(tmp, crate)
    vault = make_vault(tmp / "target-vault")
    manifest = manifest_with([{**BOARDS, "default": "synth-boards"}])
    locations = replace(crate.world.locations, state_dir=install.state, plugin_manifests=(manifest,),
                        plugin_settings={PLUGIN: {"boardsRoot": ""}}, plugin_enabled={PLUGIN: True})
    homes = plugin_homes_of(locations)
    default = install.state / "synth-boards"
    env = replace(install.env, plugin_homes=homes, relink_board=relinker(default, []), backup_sources=lambda: [BackupTranscripts(vault=lambda: vault)])
    return replace(install, env=env), default, vault


def test_a_blank_boards_setting_still_restores_the_boards_and_their_backup_family(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, default, vault = wired_default(tmp_path, crate)
    assert not default.exists()
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
    assert plan["ok"], plan["blockers"]
    row = plan["backups"]["folders"][0]
    assert (row["unit"], row["status"], row["reason"]) == (UNIT, "restore", None), row
    assert [s["decision"] for s in plan["plugin_data"]] == ["restore"] and not default.exists(), "the plan writes nothing"
    hooks, import_id = RecordingHooks(), new_import_id()
    receipt = run(crate, install, hooks=hooks, import_id=import_id)
    assert not receipt.plugin_data["not_restored"] and receipt.backups["folders"]["adopted"] == 2, receipt.backups
    assert (default / task_folders.ROOT_MARKER).is_file()
    held = points_of(vault)
    assert len(held) == 2 and all(m.working_dir == str(default) for m in held.values())
    fb.register("folder-import-target", BackupTranscripts(vault=lambda: vault))
    try:
        report = ap.recover_files(hooks.log, install.env, import_id)
    finally:
        fb.unregister("folder-import-target")
    assert not report.errors, report
    assert points_of(vault) == {}, "the undo took the filed points back"
    assert not [p for p in default.rglob("sidecar.json")], "and the boards"
