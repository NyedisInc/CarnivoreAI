
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.crate_import import hooks as hk
from src.core.crate_import import project_files_in
from src.core.crate_import.model import ImportFailed, ImportRequest
from src.core.crate_import.plan import build_plan
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.test_import_plan import target
from tests.python.crate_import.test_import_project_files import project_crate, restore, sides
from tests.python.crate_import.test_import_same_path import Faults, rows_of, run


def relocated(tmp: Path, name: str):
    tmp.mkdir(parents=True, exist_ok=True)
    crate = project_crate(tmp)
    install = target(tmp, crate)
    new_root = Path(install.projects) / name
    return crate, install, ImportRequest(mode="relocate", new_root=str(new_root), include_project_files=True), new_root


def test_an_empty_or_new_root_receives_the_files(tmp_path: Path) -> None:
    crate, install, request, new_root = relocated(tmp_path, "fresh")
    plan, receipt = restore(crate, install, request)
    assert plan["project_folder"] == {"path": str(new_root), "create": True, "files": "into_project_folder", "side": None}
    assert receipt.state in ("done", "done_with_warnings"), receipt
    assert (new_root / "src/app.py").read_bytes() == b"print('one')\n" and not sides(new_root)
    assert receipt.project_files["placement"] == "into_project_folder"
    crate2, install2, request2, root2 = relocated(tmp_path / "two", "empty")
    root2.mkdir(parents=True)
    plan2, _receipt2 = restore(crate2, install2, request2)
    assert plan2["project_folder"]["files"] == "into_project_folder" and plan2["project_folder"]["create"] is False
    assert (root2 / "README.md").exists() and not sides(root2)


def test_a_root_that_holds_files_gets_the_files_beside_it(tmp_path: Path) -> None:
    crate, install, request, new_root = relocated(tmp_path, "busy")
    new_root.mkdir(parents=True)
    (new_root / "mine.txt").write_bytes(b"keep me")
    plan, receipt = restore(crate, install, request)
    assert plan["project_folder"]["files"] == "beside_project_folder" and plan["project_folder"]["side"]
    (side,) = sides(new_root)
    assert (side / "src/app.py").exists() and str(side) == plan["project_folder"]["side"]
    assert not (new_root / "src").exists() and (new_root / "mine.txt").read_bytes() == b"keep me"
    assert receipt.project_files["placement"] == "beside_project_folder"


def test_an_existing_file_is_never_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    crate, install, request, new_root = relocated(tmp_path, "race")
    new_root.mkdir(parents=True)
    (new_root / "README.md").write_bytes(b"someone else's work")
    monkeypatch.setattr(project_files_in, "root_is_free", lambda root: True)
    with pytest.raises(ImportFailed):
        run(crate, install, request=request)
    assert (new_root / "README.md").read_bytes() == b"someone else's work"
    assert not (new_root / "src/app.py").exists(), "the files placed before the clash were undone"


def test_the_project_folder_is_made_and_undone(tmp_path: Path) -> None:
    crate, install, request, new_root = relocated(tmp_path, "newroot")
    request = ImportRequest(mode="relocate", new_root=str(new_root))
    receipt = run(crate, install, request=request)
    assert receipt.state in ("done", "done_with_warnings") and new_root.is_dir() and not (new_root / "src").exists()
    (project,) = rows_of(install, "SELECT root FROM projects")
    assert project["root"] == str(new_root)
    crate2, install2, request2, root2 = relocated(tmp_path / "two", "newroot")
    hooks = Faults(hk.CP_BEFORE_COMMIT, RuntimeError("stop"))
    with pytest.raises(Exception):
        run(crate2, install2, hooks=hooks, request=request2)
    assert not root2.exists(), "the folder made for the project was not removed"
    assert any(e.get("project_root") for e in hooks.log if e["op"] == "dir"), hooks.log


def test_files_already_on_disk_are_reported_here_and_nothing_is_written(tmp_path: Path) -> None:
    crate, install, request, new_root = relocated(tmp_path, "again")
    restore(crate, install, request)
    before = sorted(p.relative_to(new_root).as_posix() for p in new_root.rglob("*"))
    plan, receipt = restore(crate, install, request)
    folder = plan["project_folder"]
    assert folder["files"] == "already_here" and folder["side"] is None and plan["files"]["side_folder"]["matching"] >= 2
    assert plan["files"]["side_folder"]["differing"] == 0
    assert not sides(new_root) and sorted(p.relative_to(new_root).as_posix() for p in new_root.rglob("*")) == before
    assert receipt.project_files["placement"] == "already_here"
    (new_root / "README.md").write_bytes(b"edited")
    plan2, _receipt2 = restore(crate, install, request)
    assert plan2["project_folder"]["files"] == "beside_project_folder"
    assert plan2["files"]["side_folder"]["differing"] == 1 and plan2["files"]["side_folder"]["matching"] >= 1
    assert (new_root / "README.md").read_bytes() == b"edited"


def test_a_conversation_whose_files_are_all_kept_is_not_restored_never_write() -> None:
    from types import SimpleNamespace

    from src.core.crate_import import analysis
    from src.core.crate_import.model import Collector

    kept = SimpleNamespace(record=SimpleNamespace(conversation_id="39518d3d", role="conflict_copy"), cls=None)
    record = SimpleNamespace(id="39518d3d")
    live = SimpleNamespace(live_conversations=set())
    got = analysis.conversation_class(record, [kept], ImportRequest(), live, Collector(), False)
    assert got == "not_restored"
