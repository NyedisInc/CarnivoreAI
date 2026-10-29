
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.deepsearch import fallback_hook as fb
from src.cplugs.crate import constants as K
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.registry import CPLUGS
from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.inventory.world import UUID_A
from tests.python.cplugs.crate.test_plugin_data import (
    OWN_ONLY_KEPT, PLUGIN, SLUG_LOOSE, SLUG_MINE, SLUG_NESTED, SLUG_THEIRS, board, manifest_with, marker)

VAULTED = {**OWN_ONLY_KEPT, "backup": "vault"}
BOARDS = {"id": "boards", "kind": "folder", "root_setting": "boardsRoot", "scope_by": "task_item_id", "policy": VAULTED}
DRAFTS = {"id": "drafts", "kind": "folder", "path": "drafts", "scope_by": "install",
          "policy": {"own": "carried", "share": "excluded", "reason": "half-typed notes of this install", "backup": "vault"}}
UNIT = f"{PLUGIN}.boards"


def make_vault(root: Path) -> Vault:
    root.mkdir(parents=True, exist_ok=True)
    (root / "VAULT.json").write_text('{"format": 1}')
    return Vault(root)


@pytest.fixture
def rig(tmp_path: Path):
    w = make_world(tmp_path)
    root = tmp_path / "boards-root"
    board(root, SLUG_MINE, w.item_p)
    board(root, SLUG_THEIRS, w.item_d)
    board(root, SLUG_LOOSE, None)
    nested = root / f"proj-{w.p1}"
    marker(nested, ".tm-project", {"list": str(w.p1)})
    marker(nested / f"task-{w.item_b}", ".tm-task", {"item_id": w.item_b})
    board(nested / f"task-{w.item_b}" / "boards", SLUG_NESTED, None)
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    drafts = Path(w.state) / "cplugs" / PLUGIN / "drafts"
    drafts.mkdir(parents=True)
    (drafts / f"{SLUG_MINE}.json").write_text('{"rev": 1}')
    w.boards_root = root
    w.vault = make_vault(tmp_path / "vault")
    assert w.vault.capture_folder(UNIT, root).status == "written"
    assert w.vault.capture_folder(f"{PLUGIN}.drafts", drafts).status == "written"
    (root / SLUG_MINE / "view.html").write_text("<p>round two</p>")
    board(root, "20261015-later-theirs", w.item_d)
    assert w.vault.capture_folder(UNIT, root).status == "written"
    use(w)
    fb.register("folder-backups-test", BackupTranscripts(vault=lambda: w.vault))
    yield w
    fb.unregister("folder-backups-test")


def use(w: SimpleNamespace, *, plugin_on: bool = True, switched_off: str = "") -> None:
    save = next(d.manifest for d in CPLUGS if d.id == "save")
    synth = manifest_with([BOARDS, DRAFTS])
    w.locations = dataclasses.replace(
        w.locations, plugin_manifests=(synth, save), plugin_enabled={PLUGIN: plugin_on, "save": True},
        plugin_settings={PLUGIN: {"boardsRoot": str(w.boards_root)}, "save": {"vaultFolderOptOut": switched_off}})


def carried_rels(plan: Any) -> List[str]:
    out = set()
    for f in plan.files:
        if f.rel.endswith("/point.json") and f.backup_unit:
            out |= {item["rel"] for item in json.loads(f.inline)["files"]}
    return sorted(out)


def test_the_families_come_from_the_contract_and_grey_out_with_a_reason(rig: SimpleNamespace) -> None:
    from src.cplugs.crate import service

    inv = cs.resolve("project", rig.root1, rig.locations)
    families = {f["unit"]: f for f in cs.backup_families(inv, rig.locations)}
    assert list(families) == [UNIT], "the drafts are scoped to the install: never offered for a project crate"
    assert families[UNIT]["state"] == "ok" and families[UNIT]["plugin"] == PLUGIN and families[UNIT]["scope_by"] == "task_item_id"
    assert {Path(u["rel"]).name for u in families[UNIT]["units"] if u["dir"]} == {SLUG_MINE, SLUG_NESTED}
    use(rig, switched_off=f"{UNIT}")
    assert cs.backup_families(cs.resolve("project", rig.root1, rig.locations), rig.locations)[0]["state"] == "switched_off"
    use(rig, plugin_on=False)
    assert cs.backup_families(cs.resolve("project", rig.root1, rig.locations), rig.locations)[0]["state"] == "plugin_off"
    use(rig)
    answer = service.families_now(env_for(rig), "project", rig.root1)
    assert answer["conversations"]["available"] is True and [f["unit"] for f in answer["folders"]] == [UNIT]
    assert "root" not in answer["folders"][0]
    assert service.families_now(env_for(rig), "session", UUID_A)["folders"] == [], "a session owns no review boards"


def test_a_ticked_folder_carries_only_this_projects_boards(rig: SimpleNamespace, tmp_path: Path) -> None:
    env = env_for(rig)
    none = build_plan(env, project_request(rig))
    assert none.ok and carried_rels(none) == [] and none.backup_families == []
    plan = build_plan(env, project_request(rig, backup_units=(UNIT,)))
    assert plan.ok, plan.blockers
    rels = carried_rels(plan)
    mine = [r for r in rels if SLUG_MINE in r]
    assert mine and all(r.startswith(f"{SLUG_MINE}/") for r in mine)
    assert any(f"/boards/{SLUG_NESTED}/" in r for r in rels)
    assert not [r for r in rels if SLUG_THEIRS in r or SLUG_LOOSE in r or "later-theirs" in r or r.startswith(".git")]
    (summary,) = plan.backup_families
    assert (summary["unit"], summary["plugin"], summary["points"]) == (UNIT, PLUGIN, 2)
    assert {f.backup_unit for f in plan.files if f.backup_unit} == {UNIT} and {f.provides for f in plan.files if f.backup_unit} == {"backup_points"}
    result = run_export(env, plan, JobHandle("fb"))
    assert cf.verify(result.path, "drill", expected_sha256=result.sha256, scratch=tmp_path).ok
    with cf.open_crate(result.path) as reader:
        assert reader.manifest.extra["backup_families"]["folders"][0]["unit"] == UNIT
        assert reader.manifest.extra["backup_families"]["conversations"] is False
        stamped = [r for r in reader.files() if r.extra.get("backup_unit")]
        assert stamped and {r.home for r in stamped} == {"plugin-save"} and {r.extra["backup_unit"] for r in stamped} == {UNIT}


def test_a_greyed_or_unknown_family_that_is_ticked_is_a_blocker(rig: SimpleNamespace) -> None:
    use(rig, switched_off=UNIT)
    plan = build_plan(env_for(rig), project_request(rig, backup_units=(UNIT,)))
    assert [b["code"] for b in plan.blockers] == [K.B_BACKUP_FOLDER_OFF] and carried_rels(plan) == []
    use(rig, plugin_on=False)
    assert [b["code"] for b in build_plan(env_for(rig), project_request(rig, backup_units=(UNIT,))).blockers] == [K.B_BACKUP_FOLDER_OFF]
    use(rig)
    unknown = build_plan(env_for(rig), project_request(rig, backup_units=(f"{PLUGIN}.drafts",)))
    assert [b["code"] for b in unknown.blockers] == [K.B_BACKUP_FOLDER_UNKNOWN]


def test_a_share_never_carries_folder_backups(rig: SimpleNamespace) -> None:
    with pytest.raises(ValueError):
        build_plan(env_for(rig), project_request(rig, "share", backup_units=(UNIT,)))
