
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.crate_import import apply as ap
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.crate_import.install import Install
from tests.python.crate_import.test_import_plan import target
from tests.python.crate_import.test_import_same_path import rows_of


def project_crate(tmp: Path) -> SimpleNamespace:
    (tmp / "w").mkdir()
    world = make_world(tmp / "w")
    root = Path(world.root1)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src/app.py").write_bytes(b"print('one')\n")
    (root / "README.md").write_bytes(b"# app\n")
    os.symlink("src/app.py", root / "latest")
    (root / "x").mkdir(exist_ok=True)
    os.symlink("..", root / "x/up")
    os.symlink("x/up/x/up/../..", root / "esc2")
    env = env_for(world)
    plan = build_export_plan(env, project_request(world, include_project_files=True))
    assert plan.ok, plan.blockers
    result = run_export(env, plan, JobHandle("p7"))
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=world, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id)


def restore(crate: SimpleNamespace, install: Install, request: ImportRequest) -> Any:
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
        assert plan["ok"], plan["blockers"]
        receipt = ap.apply_import(reader, install.env, request, crate_sha256=crate.sha256, fingerprint=plan["fingerprint"],
                                  import_id=new_import_id())
    return plan, receipt


def sides(root: Path) -> list:
    return sorted(p for p in root.parent.iterdir() if p.name.startswith(f"{root.name}-"))


def test_files_go_to_a_new_folder_and_a_link_chain_out_of_it_is_not_made(tmp_path: Path) -> None:
    crate = project_crate(tmp_path)
    install = target(tmp_path, crate)
    root = Path(crate.world.root1)
    (root / "README.md").write_bytes(b"newer local work")
    before = (root / "src/app.py").read_bytes()
    plan, receipt = restore(crate, install, ImportRequest(include_project_files=True))
    assert receipt.state in ("done", "done_with_warnings"), receipt
    (side,) = sides(root)
    assert (side / "src/app.py").read_bytes() == before and (side / "README.md").exists()
    assert (root / "src/app.py").read_bytes() == before and not (root / ".crate-import").exists()
    assert os.readlink(side / "latest") == "src/app.py"
    assert not os.path.lexists(side / "esc2"), "a chain of links that leaves the side folder must not be made"
    real_side = os.path.realpath(side)
    for link in (p for p in side.rglob("*") if p.is_symlink()):
        assert os.path.realpath(link).startswith(real_side), f"{link} resolves outside the side folder"
    assert any(i.startswith("esc2") for i in receipt.project_files["links_not_created"])


def test_work_in_the_restored_copy_makes_it_the_project_folder(tmp_path: Path) -> None:
    crate = project_crate(tmp_path)
    install = target(tmp_path, crate)
    root = Path(crate.world.root1)
    (root / "README.md").write_bytes(b"newer local work")
    _plan, receipt = restore(crate, install, ImportRequest(include_project_files=True, work_in_restored_copy=True))
    assert receipt.state in ("done", "done_with_warnings"), receipt
    (side,) = sides(root)
    (project,) = rows_of(install, "SELECT root FROM projects")
    assert project["root"] == str(side)
    dirs = {r["working_dir"] for r in rows_of(install, "SELECT working_dir FROM sessions")}
    assert dirs and all(d == str(side) or d.startswith(f"{side}/") for d in dirs), dirs
