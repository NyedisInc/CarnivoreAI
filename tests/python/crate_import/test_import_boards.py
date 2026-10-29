
from __future__ import annotations

import copy
import json
import sqlite3
import stat
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from src.core.crate_import import analysis, apply as ap, plugin_data_in
from src.core.crate_import.env import StoreHome
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.provenance import Provenance
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.reviewboard.scan import scan
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import task_folders
from src.cplugs.sdk.crate_import import plugin_homes_of
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.cplugs.crate.test_plugin_data import manifest_with, marker
from src.cplugs.reviewboard import document
from src.cplugs.sdk.computer import local_computer
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board, make_root, sidecar
from tests.python.crate_import.test_import_same_path import rows_of, run
from tests.python.crate_import.test_import_work_side import target_install
from tests.python.inventory.world import UUID_A

PLUGIN = "synth"
KEPT = {"own": "carried", "share": "excluded", "reason": "the owner's own boards travel with the task", "purge": "kept"}
BOARDS = {"id": "boards", "kind": "folder", "root_setting": "boardsRoot", "scope_by": "task_item_id", "policy": KEPT}
MEMO = {"id": "memo", "kind": "folder", "root_setting": "otherRoot", "scope_by": "session_uuid", "policy": KEPT}
KEEP = {"id": "keep", "kind": "folder", "path": "keep", "scope_by": "session_uuid",
        "policy": {"own": "carried", "share": "excluded", "reason": "small notes named for a session"}}
SLUG_MINE, SLUG_NESTED = "20261013-mine", "20261014-nested"


def board_raw(slug: str, item: Optional[int]) -> Dict[str, Any]:
    raw = sidecar()
    raw["board"] = {**raw["board"], "slug": slug}
    raw["task"] = {**raw["task"], "item_id": item, "computer": local_computer()} if item is not None else None
    return raw


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
    memo = tmp / "memo-src"
    memo.mkdir()
    (memo / f"{UUID_A}.txt").write_text("the crate's memo\n")
    keep = Path(w.state) / "cplugs" / PLUGIN / "keep"
    keep.mkdir(parents=True)
    (keep / f"{UUID_A}.txt").write_text("the crate's note\n")
    manifest = manifest_with([BOARDS, MEMO, KEEP])
    w.locations = replace(w.locations, plugin_manifests=(manifest,), plugin_settings={PLUGIN: {"boardsRoot": str(root), "otherRoot": str(memo)}})
    env = env_for(w)
    plan = build_export_plan(env, project_request(w))
    assert plan.ok, plan.blockers
    result = run_export(env, plan, JobHandle("s6"))
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=w, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id)


def wired(tmp: Path, crate: SimpleNamespace, *, boards: bool = True, memo: bool = True, **kw: Any) -> Tuple[Any, Dict[str, Path], List[Tuple[str, int]]]:
    install = target_install(tmp, crate, **kw)
    homes: Dict[str, Path] = {}
    root = make_root(tmp / "t")
    memo_dir = tmp / "t" / "memo"
    memo_dir.mkdir()
    keep = install.state / "cplugs" / PLUGIN / "keep"
    keep.mkdir(parents=True)
    table: Dict[Tuple[str, str], StoreHome] = {(PLUGIN, "keep"): StoreHome(keep, "")}
    if boards:
        table[(PLUGIN, "boards")] = StoreHome(root, "kept")
        homes["boards"] = root
    if memo:
        table[(PLUGIN, "memo")] = StoreHome(memo_dir, "kept")
        homes["memo"] = memo_dir
    homes["keep"] = keep
    calls: List[Tuple[str, int]] = []
    env = replace(install.env, plugin_homes=lambda plugin, data: table.get((plugin, data)), relink_board=relinker(root, calls))
    return replace(install, env=env), homes, calls


def relinker(root: Path, calls: List[Tuple[str, int]], works: bool = True):  # noqa: ANN201
    def relink(slug: str, item: int) -> bool:
        calls.append((slug, item))
        board = plugin_data_in.find_board(root, slug)
        if not works or board is None:
            return False
        raw = json.loads((board / "sidecar.json").read_text())
        raw["task"] = {**SIDECAR["task"], "item_id": item}
        (board / "sidecar.json").write_text(document.canonical_text(document.parse_sidecar(raw)), encoding="utf-8")
        return True
    return relink


def new_item_of(install: Any, old_text_id: int) -> int:
    return rows_of(install, "SELECT id FROM work_items WHERE text = ?", f"item {old_text_id}")[0]["id"]


def test_a_board_is_placed_in_its_new_task_folder_and_relinked(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, calls = wired(tmp_path, crate)
    receipt = run(crate, install, request=ImportRequest())
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    w = crate.world
    new_p, new_b = new_item_of(install, w.item_p), new_item_of(install, w.item_b)
    assert new_p != w.item_p
    root = homes["boards"]
    for item, slug in ((new_p, SLUG_MINE), (new_b, SLUG_NESTED)):
        task = task_folders.find_task(root, item)
        assert task is not None and task_folders.task_item_of(task) == item
        assert (task / "boards" / slug / "sidecar.json").is_file() and (task / "boards" / slug / "r001.html").is_file()
    assert not (root / SLUG_MINE).exists() and not (root / f"proj-{w.p1}").exists()
    assert sorted(calls) == sorted([(SLUG_MINE, new_p), (SLUG_NESTED, new_b)])
    assert {b["slug"]: b["relinked"] for b in receipt.plugin_data["boards"]} == {SLUG_MINE: True, SLUG_NESTED: True}
    result = scan(root)
    assert result.exit_code == 0 and not [f for f in result.findings if f.severity == "error"], result.findings


def test_a_board_already_there_wins_and_the_crate_copy_goes_beside_it(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, calls = wired(tmp_path, crate)
    root = homes["boards"]
    other = board_raw(SLUG_MINE, None)
    other["board"]["title"] = "a different board with the same slug"
    make_board(root, other)
    twin = copy.deepcopy(board_raw(SLUG_NESTED, None))
    make_board(root, twin)
    before = (root / SLUG_MINE / "sidecar.json").read_bytes()
    import_id = new_import_id()
    receipt = run(crate, install, import_id=import_id)
    states = {b["slug"]: b["state"] for b in receipt.plugin_data["boards"]}
    assert states == {SLUG_MINE: "beside", SLUG_NESTED: "same"}
    assert (root / SLUG_MINE / "sidecar.json").read_bytes() == before
    beside = root / ".crate-import" / import_id / "boards" / SLUG_MINE
    assert (beside / "sidecar.json").is_file() and json.loads((beside / "sidecar.json").read_text())["board"]["title"] != other["board"]["title"]
    assert not calls
    result = scan(root)
    assert result.exit_code == 0 and not [f for f in result.findings if f.severity == "error"], result.findings


def test_a_board_store_with_no_folder_is_listed_not_restored_and_other_stores_stay_in_the_receipt(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, calls = wired(tmp_path, crate, boards=False, memo=False)
    import_id = new_import_id()
    receipt = run(crate, install, import_id=import_id)
    assert receipt.state in ("done", "done_with_warnings")
    assert receipt.plugin_data["unlocated"] == ["synth.memo"]
    assert receipt.plugin_data["not_restored"] == [{"what": "plugin_data:synth.boards", "why": "plugin_store_no_folder"}]
    codes = {w["code"] for w in receipt.warnings}
    assert {"plugin_store_unlocated", "plugin_store_no_folder"} <= codes
    kept = install.env.backup_dir(import_id).parent / "plugin-data" / PLUGIN
    assert not (kept / "boards").exists() and (kept / "memo" / f"{UUID_A}.txt").read_text() == "the crate's memo\n"
    assert not calls


def test_boards_land_in_the_default_folder_when_the_setting_is_blank(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, _homes, calls = wired(tmp_path, crate)
    default_boards = {**BOARDS, "default": "synth-boards"}
    manifest = manifest_with([default_boards, MEMO, KEEP])
    locations = replace(crate.world.locations, state_dir=install.state, plugin_manifests=(manifest,),
                        plugin_settings={PLUGIN: {"boardsRoot": ""}}, plugin_enabled={PLUGIN: True})
    homes = plugin_homes_of(locations)
    home = homes(PLUGIN, "boards")
    assert home is not None and home.default and home.root == install.state / "synth-boards" and not home.root.exists()
    env = replace(install.env, plugin_homes=lambda plugin, data: homes(plugin, data) if data == "boards" else install.env.plugin_homes(plugin, data),
                  relink_board=relinker(home.root, calls))
    receipt = run(crate, replace(install, env=env))
    assert not receipt.plugin_data["not_restored"] and "plugin_store_no_folder" not in {w["code"] for w in receipt.warnings}
    assert (home.root / task_folders.ROOT_MARKER).is_file() and stat.S_IMODE(home.root.stat().st_mode) == 0o700
    assert plugin_data_in.find_board(home.root, SLUG_MINE) is not None and plugin_data_in.find_board(home.root, SLUG_NESTED) is not None
    result = scan(home.root)
    assert result.exit_code == 0 and not [f for f in result.findings if f.severity == "error"], result.findings


def test_a_board_store_of_a_plugin_that_is_off_is_not_restored_even_with_a_folder(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, calls = wired(tmp_path, crate)
    install = replace(install, env=replace(install.env, plugin_enabled=lambda plugin: False))
    receipt = run(crate, install)
    assert receipt.plugin_data["not_restored"] == [{"what": "plugin_data:synth.boards", "why": "plugin_store_plugin_off"}]
    assert plugin_data_in.find_board(homes["boards"], SLUG_MINE) is None and not calls
    with cf.open_crate(crate.path) as reader:
        rows = {v["store"]: v for v in plugin_data_in.preview(plugin_data_in.stores_of(reader), install.env, True)}
    assert (rows["synth.boards"]["decision"], rows["synth.boards"]["reason"]) == ("unlocated", "plugin_store_plugin_off")
    assert rows["synth.memo"]["decision"] == "restore" and rows["synth.memo"]["reason"] is None


def test_purge_kept_and_plain_stores(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, calls = wired(tmp_path, crate)
    (homes["memo"] / f"{UUID_A}.txt").write_text("what is already here\n")
    (homes["keep"] / f"{UUID_A}.txt").write_text("a local note\n")
    import_id = new_import_id()
    receipt = run(crate, install, import_id=import_id)
    assert (homes["memo"] / f"{UUID_A}.txt").read_text() == "what is already here\n"
    assert (homes["memo"] / ".crate-import" / import_id / "memo" / f"{UUID_A}.txt").read_text() == "the crate's memo\n"
    assert (homes["keep"] / f"{UUID_A}.txt").read_text() == "a local note\n"
    assert not (homes["keep"] / ".crate-import").exists()
    assert str(homes["keep"] / f"{UUID_A}.txt") in receipt.plugin_data["kept"]


def test_running_the_step_again_places_nothing_new(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, calls = wired(tmp_path, crate)
    import_id = new_import_id()
    run(crate, install, import_id=import_id)
    tree = sorted(p.relative_to(homes["boards"]).as_posix() for p in homes["boards"].rglob("*") if p.is_file())
    first_calls = list(calls)
    with cf.open_crate(crate.path) as reader:
        again = ap.finish_import(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, import_id=import_id)
    assert sorted(p.relative_to(homes["boards"]).as_posix() for p in homes["boards"].rglob("*") if p.is_file()) == tree
    assert {b["state"] for b in again.plugin_data["boards"]} == {"same"} and again.plugin_data["written"] == 0
    assert calls == first_calls


def test_plugin_data_of_a_foreign_crate_needs_the_tick() -> None:
    own = Provenance(kind="own_verified", reason="written_here", claims_this_install=True)
    foreign = Provenance(kind="foreign", reason="other_computer", claims_this_install=False)
    assert analysis.restores_plugin_data(ImportRequest(), own) is True
    assert analysis.restores_plugin_data(ImportRequest(), foreign) is False
    assert analysis.restores_plugin_data(ImportRequest(include_plugin_data=True), foreign) is True


def test_a_relink_that_failed_is_retried_and_one_that_worked_is_not_copied_beside(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, calls = wired(tmp_path, crate)
    root = homes["boards"]
    failing = replace(install, env=replace(install.env, relink_board=relinker(root, calls, works=False)))
    first = run(crate, failing)
    assert {b["relinked"] for b in first.plugin_data["boards"]} == {False} and len(calls) == 2
    calls.clear()
    second = run(crate, install)
    assert sorted(slug for slug, _item in calls) == sorted([SLUG_MINE, SLUG_NESTED]), calls
    assert second.state == "done_with_warnings" or second.state == "done"
    calls.clear()
    third = run(crate, install)
    assert not calls and third.state == "noop"
    assert not (root / ".crate-import").exists(), "a relinked board must not be copied beside itself"


def test_the_real_import_env_carries_a_relink_hook_that_reaches_the_boards_port(tmp_path: Path) -> None:
    from src.core.crate_import.env import no_relink
    from src.core.project_move.plan import PaneListing
    from src.cplugs.sdk import crate_import as sdk, ports

    w = make_world(tmp_path)
    env = sdk.import_env(Path(w.state), w.locations, "i", lambda: PaneListing(True))
    assert env.relink_board is not no_relink and env.relink_board("s", 1) is False
    asked: List[Tuple[str, int]] = []
    ports.register(sdk.RELINK_PORT, SimpleNamespace(relink=lambda slug, item: asked.append((slug, item)) or True))
    try:
        assert env.relink_board("20261019-crate-carry-test", 1) is True
    finally:
        ports.unregister(sdk.RELINK_PORT)
    assert asked == [("20261019-crate-carry-test", 1)]


def test_a_relink_owed_again_is_undone_to_the_old_bytes_and_a_placed_board_is_removed(tmp_path: Path) -> None:
    from src.core.crate_import import undo
    from src.core.crate_import.plugin_data_in import Store

    root = make_root(tmp_path)
    store = Store("synth", "boards")
    old = (make_board(root, board_raw("20261019-a-board", 1027)) / "sidecar.json")
    before = old.read_bytes()
    relinker(root, [], True)("20261019-a-board", 1)
    assert old.read_bytes() != before
    entries: List[Dict[str, Any]] = []
    plugin_data_in._log_relinked_sidecar(old, entries.append, store, before, tmp_path / "keep")
    report = undo.rollback(entries, [root])
    assert old.read_bytes() == before and str(old) in report.removed
    placed = (make_board(root, board_raw("20261019-b-board", 1027)) / "sidecar.json")
    plugin_data_in._log_relinked_sidecar(placed, entries.append, store)
    undo.rollback(entries[-1:], [root])
    assert not placed.exists()
