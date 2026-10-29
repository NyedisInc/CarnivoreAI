
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.crate_import import apply as ap
from src.core.crate_import import undo
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.deepsearch import fallback_hook as fb
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.vault import units
from src.cplugs.save.vault.identity import Identity
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.crate_import.test_import_plan import target
from tests.python.crate_import.test_import_same_path import rows_of


def make_vault(root: Path) -> Vault:
    root.mkdir(parents=True, exist_ok=True)
    (root / "VAULT.json").write_text('{"format": 1}')
    return Vault(root)


def vault_crate(tmp: Path, *, backups: bool = True) -> SimpleNamespace:
    (tmp / "w").mkdir()
    world = make_world(tmp / "w")
    world.locations = dataclasses.replace(world.locations, plugin_enabled={"save": True})
    vault = make_vault(tmp / "source-vault")
    sources = units.Sources((Path(world.home) / "projects",), Path(world.codex), Path(world.state))
    convs = sorted({p.stem for p in (Path(world.home) / "projects").rglob("*.jsonl") if "/" not in p.stem and len(p.stem) > 20})
    taken = []
    for conv in convs:
        plan = units.plan_claude(sources, conv)
        if plan is None:
            continue
        assert vault.capture(plan, Identity(), "kill").status == "written"
        killed = vault.manifests.point_ids(conv)[-1]
        vault.manifests.set_pinned(conv, killed, True)
        main = next(p for p in (Path(world.home) / "projects").rglob(f"{conv}.jsonl"))
        with open(main, "ab") as handle:
            handle.write(b'{"type":"user","n":9999}\n')
        assert vault.capture(units.plan_claude(sources, conv), Identity(), "follow").status == "written"
        vault.manifests.set_pinned(conv, killed, False)
        taken.append(conv)
    assert taken, "the world has no conversation"
    source = BackupTranscripts(vault=lambda: vault)
    fb.register("save-test-source", source)
    try:
        env = env_for(world)
        plan = build_export_plan(env, project_request(world, include_backups=backups))
        assert plan.ok, plan.blockers
        result = run_export(env, plan, JobHandle("b1"))
    finally:
        fb.unregister("save-test-source")
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=world, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id,
                           vault=vault, convs=[c for c in taken if c in {x['id'] for x in plan.conversations}], plan=plan)


def restore_with(crate: SimpleNamespace, install: Any, sources: List[Any], request: ImportRequest = ImportRequest(), hooks: Any = None) -> Any:
    install.env = install.env.__class__(**{**install.env.__dict__, "backup_sources": lambda: sources})
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
        assert plan["ok"], plan["blockers"]
        receipt = ap.apply_import(reader, install.env, request, crate_sha256=crate.sha256, fingerprint=plan["fingerprint"],
                                  import_id=new_import_id(), hooks=hooks)
    return plan, receipt


def points_of(vault: Vault, conv: str) -> Dict[str, Any]:
    return {m.point_id: m for m in vault.manifests.points(conv)}


def test_the_round_trip_files_every_point(tmp_path: Path) -> None:
    crate = vault_crate(tmp_path)
    install = target(tmp_path, crate)
    vault = make_vault(tmp_path / "target-vault")
    plan, receipt = restore_with(crate, install, [BackupTranscripts(vault=lambda: vault)])
    assert plan["backups"]["carried"] and plan["backups"]["restores"]
    assert {r["status"] for r in plan["backups"]["conversations"]} == {"restore"}
    assert receipt.backups["adopted"] == 2 * len(crate.convs) and receipt.backups["refused"] == []
    for conv in crate.convs:
        assert set(points_of(vault, conv)) == set(points_of(crate.vault, conv))
        for manifest in points_of(vault, conv).values():
            assert vault.manifests.is_kept(conv, manifest.point_id)
            for entry in manifest.files:
                raw = b"".join(vault.blobs.get(c) for c in entry.chunks)
                assert len(raw) == entry.length
    again_plan, again = restore_with(crate, install, [BackupTranscripts(vault=lambda: vault)])
    assert again.backups["adopted"] == 0 and {r["status"] for r in again_plan["backups"]["conversations"]} == {"present"}
    assert again.backups["present"] == 2 * len(crate.convs)


def test_plugin_off_lists_the_backups_as_not_restored(tmp_path: Path) -> None:
    crate = vault_crate(tmp_path)
    install = target(tmp_path, crate)
    plan, receipt = restore_with(crate, install, [])
    assert {r["reason"] for r in plan["backups"]["conversations"]} == {"backup_plugin_off"}
    assert {n["why"] for n in plan["not_restored"] if n["what"].startswith("backups:")} == {"backup_plugin_off"}
    assert receipt.backups["adopted"] == 0 and len(receipt.backups["not_restored"]) == len(crate.convs)


def test_a_crate_without_the_tick_carries_no_backups(tmp_path: Path) -> None:
    crate = vault_crate(tmp_path, backups=False)
    install = target(tmp_path, crate)
    vault = make_vault(tmp_path / "target-vault")
    plan, receipt = restore_with(crate, install, [BackupTranscripts(vault=lambda: vault)])
    assert plan["backups"]["carried"] is False and vault.manifests.units() == [] and receipt.backups == {}


def test_an_undo_removes_only_the_filed_points(tmp_path: Path) -> None:
    crate = vault_crate(tmp_path)
    install = target(tmp_path, crate)
    vault = make_vault(tmp_path / "target-vault")
    conv = crate.convs[0]
    own = vault.capture(units.plan_claude(units.Sources((Path(crate.world.home) / "projects",), Path(crate.world.codex), Path(crate.world.state)), conv),
                        Identity(), "sleep")
    assert own.status == "written"
    before = set(points_of(vault, conv))
    log: List[dict] = []

    class Logging(hk_cls()):
        def undo(self, entry: Dict[str, Any]) -> None:
            log.append(entry)

    source = BackupTranscripts(vault=lambda: vault)
    restore_with(crate, install, [source], hooks=Logging())
    assert len(set(points_of(vault, conv))) > len(before)
    fb.register("save-test-target", source)
    try:
        report = undo.rollback([e for e in log if e.get("op") == undo.OP_VAULT], [])
    finally:
        fb.unregister("save-test-target")
    assert set(points_of(vault, conv)) == before and report.errors == []
    for other in crate.convs[1:]:
        assert points_of(vault, other) == {}


def hk_cls() -> type:
    from src.core.crate_import import hooks as hk

    return hk.ApplyHooks


def test_a_relocated_project_files_its_backups_under_the_new_folder(tmp_path: Path) -> None:
    crate = vault_crate(tmp_path)
    install = target(tmp_path, crate)
    vault = make_vault(tmp_path / "target-vault")
    new_root = Path(install.projects) / "moved"
    plan, receipt = restore_with(crate, install, [BackupTranscripts(vault=lambda: vault)], ImportRequest(mode="relocate", new_root=str(new_root)))
    assert receipt.backups["adopted"] == 2 * len(crate.convs)
    enc_targets = {e["to"] for e in plan["enc"]}
    assert enc_targets and not enc_targets & {e["from"] for e in plan["enc"]}
    for conv in crate.convs:
        for manifest in points_of(vault, conv).values():
            homes = {f.rel.split("/")[1] for f in manifest.files if f.rel.startswith("projects/")}
            assert homes <= enc_targets, (homes, enc_targets)
            assert all(f.source_path.startswith(str(install.claude)) for f in manifest.files if f.home == "claude")


def test_a_foreign_crate_files_its_backups_only_when_the_owner_ticks(tmp_path: Path) -> None:
    crate = vault_crate(tmp_path)
    (tmp_path / "off").mkdir()
    off_install = target(tmp_path / "off", crate, mark=False)
    vault_off = make_vault(tmp_path / "vault-off")
    plan, receipt = restore_with(crate, off_install, [BackupTranscripts(vault=lambda: vault_off)],
                                 ImportRequest(mode="relocate", new_root=str(Path(off_install.projects) / "moved")))
    assert plan["provenance"] == "foreign"
    assert {r["reason"] for r in plan["backups"]["conversations"]} == {"backups_not_chosen"}
    assert vault_off.manifests.units() == [] and receipt.backups["adopted"] == 0
    (tmp_path / "on").mkdir()
    on_install = target(tmp_path / "on", crate, mark=False)
    vault_on = make_vault(tmp_path / "vault-on")
    plan, receipt = restore_with(crate, on_install, [BackupTranscripts(vault=lambda: vault_on)],
                                 ImportRequest(mode="relocate", new_root=str(Path(on_install.projects) / "moved"), file_backups=True))
    assert receipt.backups["adopted"] == 2 * len(crate.convs)
    for conv in crate.convs:
        assert set(points_of(vault_on, conv)) == set(points_of(crate.vault, conv))
        assert all(vault_on.manifests.is_kept(conv, p) for p in points_of(vault_on, conv))


def test_the_mcp_path_ignores_the_backups_tick() -> None:
    from src.cplugs.crate import imports

    body = {"mode": "same_paths", "file_backups": True, "made_here": True}
    assert imports.request_of(body, allow_made_here=True).file_backups is True
    assert imports.request_of(body, allow_made_here=False).file_backups is False
