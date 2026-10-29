
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.inventory import plugin_claims, plugin_stores, plugin_units, registry, registry_side, state_files
from src.core.inventory.locations import Locations
from src.cplugs.crate import constants as K
from src.cplugs.crate import policy as P
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.project_files import walk_project
from src.cplugs.crate.writer import run_export
from src.cplugs.reviewboard import CPLUG as REVIEWBOARD
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.cplugs.sdk import data_decl
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request, session_request
from tests.python.inventory.world import UUID_A

PLUGIN = "synth"
SETTINGS = {"boardsRoot": {"kind": "string", "default": ""}, "otherRoot": {"kind": "string", "default": ""},
            "outRoot": {"kind": "string", "default": ""}}
OWN_ONLY = {"own": "carried", "share": "excluded", "reason": "the owner's own boards travel with the task"}
OWN_ONLY_KEPT = {**OWN_ONLY, "purge": "kept"}
BOARDS = {"id": "boards", "kind": "folder", "root_setting": "boardsRoot", "scope_by": "task_item_id", "policy": OWN_ONLY_KEPT}
DRAFTS = {"id": "drafts", "kind": "folder", "path": "drafts", "scope_by": "task_item_id", "policy": OWN_ONLY}
CACHE = {"id": "cache", "kind": "db", "path": "cache.db", "scope_by": "install",
         "policy": {"own": "excluded", "share": "excluded", "reason": "a cache of this install"}}
UNSET = {"id": "elsewhere", "kind": "folder", "root_setting": "otherRoot", "scope_by": "session_uuid", "policy": OWN_ONLY_KEPT}
SLUG_MINE, SLUG_THEIRS, SLUG_LOOSE, SLUG_NESTED = "20261013-mine", "20261013-theirs", "20261013-loose", "20261014-nested"


def manifest_with(declared: Optional[List[Dict[str, Any]]]) -> Any:
    fields = dict(SETTINGS)
    data = None if declared is None else data_decl.parse_data(declared, fields)
    return dataclasses.replace(REVIEWBOARD.manifest, id=PLUGIN, data=data, settings_schema={"version": 1, "fields": fields})


def board(root: Path, rel: str, task: Optional[int]) -> None:
    folder = root / rel
    folder.mkdir(parents=True)
    (folder / "sidecar.json").write_text(json.dumps({"task": {"item_id": task} if task is not None else None}))
    (folder / "view.html").write_text(f"<p>{rel}</p>")


def marker(folder: Path, name: str, body: Dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(body))


@pytest.fixture
def rig(tmp_path: Path) -> SimpleNamespace:
    w = make_world(tmp_path)
    root = tmp_path / "boards-root"
    board(root, SLUG_MINE, w.item_p)
    board(root, SLUG_THEIRS, w.item_d)
    board(root, SLUG_LOOSE, None)
    nested = root / f"proj-{w.p1}"
    marker(nested, ".tm-project", {"list": str(w.p1)})
    marker(nested / f"task-{w.item_b}", ".tm-task", {"item_id": w.item_b})
    board(nested / f"task-{w.item_b}" / "boards", SLUG_NESTED, None)
    drafts = Path(w.state) / "cplugs" / PLUGIN / "drafts"
    drafts.mkdir(parents=True)
    (drafts / f"{SLUG_MINE}.json").write_text('{"rev": 1}')
    (drafts / f"{SLUG_THEIRS}.json").write_text('{"rev": 1}')
    w.boards_root = root
    use(w, [BOARDS, DRAFTS, CACHE, UNSET])
    return w


def use(w: SimpleNamespace, declared: Optional[List[Dict[str, Any]]], **settings: str) -> None:
    values = {"boardsRoot": str(w.boards_root), **settings}
    w.locations = dataclasses.replace(w.locations, plugin_manifests=(manifest_with(declared),), plugin_settings={PLUGIN: values})


def files_of(plan: Any) -> List[str]:
    return sorted(f.rel for f in plan.files if f.plugin)


def view_of(plan: Any, store: str) -> Dict[str, Any]:
    return next(v for v in plan.plugin_stores if v["store"] == store)


def test_a_project_export_carries_the_boards_of_its_tasks_and_not_another_projects(rig: SimpleNamespace) -> None:
    plan = build_plan(env_for(rig), project_request(rig))
    assert plan.ok, plan.blockers
    assert files_of(plan) == sorted([
        f"boards/{SLUG_MINE}/sidecar.json", f"boards/{SLUG_MINE}/view.html",
        f"boards/proj-{rig.p1}/.tm-project", f"boards/proj-{rig.p1}/task-{rig.item_b}/.tm-task",
        f"boards/proj-{rig.p1}/task-{rig.item_b}/boards/{SLUG_NESTED}/sidecar.json",
        f"boards/proj-{rig.p1}/task-{rig.item_b}/boards/{SLUG_NESTED}/view.html",
        f"drafts/{SLUG_MINE}.json"])
    boards, drafts = view_of(plan, "synth.boards"), view_of(plan, "synth.drafts")
    assert (boards["decision"], boards["files"], boards["out_of_scope"]) == ("carry", 6, 2)
    assert (drafts["decision"], drafts["files"], drafts["out_of_scope"]) == ("carry", 1, 1)
    assert boards["bytes"] > 0 and boards["reason"] == OWN_ONLY["reason"]
    assert {r["store"] for r in plan.reconcile} >= {"synth.boards", "synth.drafts", "synth.cache", "synth.elsewhere"}


def test_the_crate_files_them_under_a_plugin_home_and_extracts_them_there(rig: SimpleNamespace, tmp_path: Path) -> None:
    env = env_for(rig)
    plan = build_plan(env, project_request(rig))
    result = run_export(env, plan, JobHandle("p"))
    assert cf.verify(result.path, "drill", expected_sha256=result.sha256, scratch=tmp_path).ok
    with cf.open_crate(result.path) as reader:
        assert reader.format_version == (1, 1)
        records = {r.rel: r for r in reader.files() if r.home == "plugin-synth"}
        mine = records[f"boards/{SLUG_MINE}/sidecar.json"]
        assert (mine.role, mine.home_index, mine.extra["plugin"], mine.extra["data"]) == ("plugin_file", 0, "synth", "boards")
        assert records[f"drafts/{SLUG_MINE}.json"].extra["data"] == "drafts"
        home = next(h for h in reader.manifest.homes if h.kind == "plugin-synth")
        assert home.path is None and home.extra["stores"]["boards"] == str(rig.boards_root.resolve())
        out = cf.extract_all(reader, tmp_path / "out")
    assert (out.dest / "plugin-synth" / "boards" / SLUG_MINE / "view.html").read_text() == f"<p>{SLUG_MINE}</p>"
    assert not (out.dest / "plugin-synth" / "boards" / SLUG_THEIRS).exists()


def test_a_session_export_lists_the_boards_as_out_of_scope(rig: SimpleNamespace) -> None:
    plan = build_plan(env_for(rig), session_request(UUID_A))
    assert files_of(plan) == []
    boards = view_of(plan, "synth.boards")
    assert boards["decision"] == "carry" and boards["files"] == 0 and boards["out_of_scope"] == 4
    row = next(r for r in plan.reconcile if r["store"] == "synth.boards")
    assert row["out_of_scope"] == 4 and "4 left out" in row["reason"]
    assert plan.ok


def test_an_undeclared_plugin_store_on_disk_fails_the_export_closed(rig: SimpleNamespace) -> None:
    use(rig, None)
    (Path(rig.state) / "cplugs" / PLUGIN / "mystery.db").write_bytes(b"")
    plan = build_plan(env_for(rig), project_request(rig))
    assert not plan.ok
    assert [b for b in plan.blockers if b["code"] == K.B_NO_POLICY and "synth.undeclared" in b["detail"]]
    assert plan.plugin_stores and plan.plugin_stores[0]["decision"] == P.BLOCKED


def test_an_undeclared_plugin_that_kept_nothing_does_not_block(rig: SimpleNamespace) -> None:
    use(rig, None)
    import shutil
    shutil.rmtree(Path(rig.state) / "cplugs" / PLUGIN / "drafts")
    assert build_plan(env_for(rig), project_request(rig)).ok


def test_an_unset_setting_is_listed_and_never_blocks(rig: SimpleNamespace) -> None:
    plan = build_plan(env_for(rig), project_request(rig))
    assert plan.ok, plan.blockers
    row = view_of(plan, "synth.elsewhere")
    assert row["decision"] == "exclude" and "otherRoot" in row["reason"] and row["files"] == 0
    assert any(r["store"] == "synth.elsewhere" and "is not set" in r["what"] for r in plan.reconcile)
    assert plugin_stores.declared_stores(rig.locations)[3].location is None


def test_a_declaration_beats_a_core_row_for_the_same_place(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    crates = Path(rig.state) / "crates"
    crates.mkdir()
    row = registry_side.ExcludedStore("crates", registry_side.K.GAP, "a stale core row for a place a plugin now declares")
    with_row = (*registry_side.EXCLUDED_STORES, row)
    monkeypatch.setattr(registry_side, "EXCLUDED_STORES", with_row)
    monkeypatch.setattr(cs, "EXCLUDED_STORES", with_row)
    registry.book.cache_clear()
    try:
        gap = lambda plan: [r for r in plan.reconcile if r["store"] == "crates"]  # noqa: E731
        before = build_plan(env_for(rig), project_request(rig))
        assert len(gap(before)) == 1 and any("crates" in w for w in before.warnings)
        use(rig, [BOARDS, DRAFTS, CACHE, UNSET, {**UNSET, "id": "out", "root_setting": "outRoot"}], outRoot=str(crates))
        after = build_plan(env_for(rig), project_request(rig))
        assert gap(after) == [] and not any("crates" in w for w in after.warnings)
        assert sum(1 for r in after.reconcile if r["store"] == "synth.out") == 1
    finally:
        monkeypatch.undo()
        registry.book.cache_clear()
    assert plugin_stores.superseded("crates", ["crates"]) and not plugin_stores.superseded("crates", ["crates2"])


def test_the_shipped_stores_are_declared_not_listed_in_core(tmp_path: Path) -> None:
    core = {s.store for s in registry_side.EXCLUDED_STORES}
    assert not core & {"cplugs/flow/flow.db", "cplugs/reviewboard/*", "cplugs/crate/jobs", "cplugs/crate/extract"}
    locs = Locations(state_dir=tmp_path, config_path=tmp_path / "config.json", plugin_settings={})
    rels = plugin_stores.declared_state_rels(locs)
    assert {"cplugs/flow/flow.db", "cplugs/crate/jobs", "cplugs/crate/extract", "cplugs/reviewboard/drafts"} <= set(rels)
    (tmp_path / "cplugs/flow").mkdir(parents=True)
    (tmp_path / "cplugs/flow/flow.db").write_bytes(b"")
    assert state_files.unaccounted(tmp_path) == []


def test_a_share_carries_none_of_it(rig: SimpleNamespace, tmp_path: Path) -> None:
    env = env_for(rig)
    plan = build_plan(env, project_request(rig, "share"))
    assert plan.ok, plan.blockers
    assert files_of(plan) == [] and view_of(plan, "synth.boards")["decision"] == "exclude"
    assert view_of(plan, "synth.boards")["reason"] == OWN_ONLY["reason"]
    result = run_export(env, plan, JobHandle("p"))
    with cf.open_crate(result.path) as reader:
        assert not [h for h in reader.manifest.homes if h.kind.startswith("plugin-")]
        assert not [r for r in reader.files() if r.home.startswith("plugin-")]


def test_the_declared_policy_decides_each_variant() -> None:
    def art(**over: Any) -> cs.Artifact:
        loc = {"plugin": PLUGIN, "data": "x", "decl_kind": "folder", "scope_by": "session_uuid",
               "policy": {"own": "carried", "share": "carried", "reason": "why"}, **over}
        return cs.Artifact(store="synth.x", kind=cs.KIND_DIR, what="/x", count=0, locator=loc)

    assert P.decide_plugin(art(), "own").action == P.CARRY and P.decide_plugin(art(), "share").action == P.CARRY
    derived = art(policy={"own": "derived", "share": "excluded", "reason": "rebuilt"})
    assert (P.decide_plugin(derived, "own").action, P.decide_plugin(derived, "share").action) == (P.DERIVED, P.EXCLUDE)
    assert P.decide_plugin(art(install_scoped=True), "own").action == P.EXCLUDE
    unscopable = P.decide_plugin(art(unscopable=True, decl_kind="db"), "own")
    assert unscopable.action == P.BLOCKED and "cannot be cut" in unscopable.reason
    assert P.decide_plugin(art(undeclared=True), "own").action == P.BLOCKED


def test_a_carried_db_is_blocked_until_it_has_row_claims(rig: SimpleNamespace) -> None:
    use(rig, [{**CACHE, "id": "log", "path": "log.db", "scope_by": "session_uuid", "policy": OWN_ONLY}])
    plan = build_plan(env_for(rig), project_request(rig))
    assert [b for b in plan.blockers if "synth.log" in b["detail"]]


def test_a_stray_backup_in_an_undeclared_plugin_folder_blocks_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "cplugs" / "huddle"
    folder.mkdir(parents=True)
    for name in ("huddle.db.bak-pre-rung12-1", "huddle.db.pre-cards-2", "notes.txt"):
        (folder / name).write_bytes(b"")
    undeclared = dataclasses.replace(next(m for m in plugin_stores.manifests_of(Locations(state_dir=tmp_path, config_path=tmp_path / "c.json", plugin_settings={})) if m.id == "huddle"), data=None)
    locs = Locations(state_dir=tmp_path, config_path=tmp_path / "config.json", plugin_settings={}, plugin_manifests=[undeclared])
    assert plugin_claims.undeclared_artifacts(locs) == []
    (folder / "mystery.db").write_bytes(b"")
    assert [a.what for a in plugin_claims.undeclared_artifacts(locs)] == [str(folder / "mystery.db")]


def test_a_board_follows_its_task_only_in_this_computers_numbering() -> None:
    mine = plugin_units.OwnerKeys("project", item_ids=frozenset({7}), list_key="7", known_item_ids=frozenset({7, 8}), here="mini")
    link = plugin_units.TaskLink
    assert mine.carries_link(link(7)) and mine.carries_link(link(7, computer="mini"))
    assert not mine.carries_link(link(8))
    assert not mine.carries_link(link(7, computer="alex-mbp"))
    assert mine.carries_link(link(7, list_key="7", computer="alex-mbp"))
    assert mine.carries_link(link(99, list_key="7"))
    assert not mine.carries_link(link(99, list_key="9")) and not mine.carries_link(link(8, list_key="7"))


def test_a_plugin_store_inside_the_project_folder_is_not_carried_twice(tmp_path: Path) -> None:
    (tmp_path / "design" / "boards").mkdir(parents=True)
    (tmp_path / "design" / "boards" / "b.json").write_text("{}")
    (tmp_path / "README.md").write_text("x")
    both = walk_project(str(tmp_path), set())
    assert {f.rel for f in both.files} == {"README.md", "design/boards/b.json"}
    walk = walk_project(str(tmp_path), set(), {str((tmp_path / "design" / "boards").resolve()): "synth.boards"})
    assert [f.rel for f in walk.files] == ["README.md"]
    assert "synth.boards" in walk.excluded()[0]["reason"]


def test_a_folder_that_cannot_be_listed_is_a_blocker_not_a_hole(rig: SimpleNamespace) -> None:
    hidden = rig.boards_root / SLUG_MINE / "rounds"
    hidden.mkdir()
    (hidden / "r1.json").write_text("{}")
    hidden.chmod(0)
    try:
        plan = build_plan(env_for(rig), project_request(rig))
    finally:
        hidden.chmod(0o755)
    assert not plan.ok and [b for b in plan.blockers if "rounds" in b["detail"]]


def test_a_root_setting_that_holds_the_state_folder_is_refused(rig: SimpleNamespace) -> None:
    use(rig, [BOARDS, DRAFTS, CACHE, UNSET], boardsRoot=str(Path(rig.state).parent))
    plan = build_plan(env_for(rig), project_request(rig))
    assert not plan.ok and [b for b in plan.blockers if "holds, a live harness home or the state folder" in b["detail"] or "inside, or holds" in b["detail"]]
    assert not [r for r in files_of(plan) if r.startswith("boards/")]


def test_locate_honors_default_state_path_and_tolerates_purge_and_role(tmp_path: Path) -> None:
    fields = {"outRoot": {"kind": "string", "default": ""}}
    kept = {**OWN_ONLY, "purge": "kept"}
    entries = [
        {"id": "out", "kind": "folder", "root_setting": "outRoot", "default": "crates", "role": "backup_destination", "scope_by": "install", "policy": kept},
        {"id": "sub", "kind": "folder", "root_setting": "outRoot", "default": "crates", "sub": "share", "scope_by": "install", "policy": kept},
        {"id": "old", "kind": "folder", "state_path": "time-machine", "scope_by": "install", "policy": kept},
        {"id": "none", "kind": "folder", "root_setting": "outRoot", "scope_by": "install", "policy": kept},
    ]
    manifest = SimpleNamespace(id="synth", settings_schema={"fields": fields})
    decls = {d.id: d for d in data_decl.parse_data(entries, fields)}
    where = lambda i, settings: plugin_stores.locate(manifest, decls[i], settings, tmp_path).location  # noqa: E731
    assert where("out", {}) == tmp_path / "crates" and where("sub", {}) == tmp_path / "crates" / "share"
    assert where("old", {}) == tmp_path / "time-machine" and where("none", {}) is None
    elsewhere = tmp_path / "elsewhere"
    assert where("out", {"outRoot": str(elsewhere)}) == elsewhere and where("sub", {"outRoot": "relative"}) is None


def test_the_save_vault_is_listed_once_when_save_declares_it(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    plan = build_plan(env_for(w), project_request(w))
    ours = [r for r in plan.reconcile if r["store"] == "save.vault"]
    assert len(ours) == 1, [r["store"] for r in plan.reconcile]
    assert not [r for r in plan.reconcile if r["store"] in ("save.vault", "vault") and r.get("action") == "carried"]
