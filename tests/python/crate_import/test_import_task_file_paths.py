
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.crate_import import apply as ap
from src.core.crate_import import ledger
from src.core.crate_import.env import StoreHome
from src.core.crate_import.model import ImportFailed, new_import_id
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.crate_import.install import Install
from tests.python.crate_import.test_import_undo_post_commit import RecordingHooks
from tests.python.crate_import.test_import_work_side import target_install
from tests.python.crate_import.test_import_same_path import rows_of, run

FILE_ID = "abcd1234"
NAME = f"{FILE_ID}-shot.png"
BYTES = b"\x89PNG task file bytes"


def paste_in(tmp: Path, *, marker: bool = True) -> Path:
    folder = tmp / "tm" / "p-1" / "t-5"
    (folder / "pastes").mkdir(parents=True)
    if marker:
        (folder / ".tm-task").write_text(json.dumps({"item_id": 5}))
    paste = folder / "pastes" / NAME
    paste.write_bytes(BYTES)
    return paste


def export_naming(tmp: Path, paths: List[str]) -> SimpleNamespace:
    (tmp / "w").mkdir()
    world = make_world(tmp / "w")
    with closing(sqlite3.connect(world.main)) as conn:
        conn.execute("UPDATE work_items SET text = 'item ' || id, created_at = 100.0 + id")
        for item, path in zip((world.item_a, world.item_b), paths):
            parts = json.dumps({"files": [{"id": FILE_ID, "name": "shot.png", "mime": "image/png", "size": len(BYTES), "path": path}]})
            conn.execute("DELETE FROM work_messages WHERE item_id = ?", (item,))
            conn.execute("INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts) "
                         "VALUES (?, 'joe', 'say', 'see file', 1.0, ?, 'k', ?)", (item, 9000 + item, parts))
        conn.commit()
    env = env_for(world)
    plan = build_export_plan(env, project_request(world))
    assert plan.ok, plan.blockers
    result = run_export(env, plan, JobHandle("t2654"))
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=world, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id)


def with_task_folder(install: Install, tmp: Path) -> Install:
    root = tmp / "tm"
    homes = lambda plugin, data: StoreHome(root, "kept") if (plugin, data) == ("reviewboard", "boards") else None  # noqa: E731
    return replace(install, env=replace(install.env, plugin_homes=homes))


def file_refs(install: Install) -> List[Dict[str, Any]]:
    return [{"item_id": r["item_id"], "path": e["path"]} for r in rows_of(install, "SELECT item_id, parts FROM work_messages WHERE parts LIKE '%files%' ORDER BY id")
            for e in json.loads(r["parts"] or "{}").get("files", [])]


def files_root(install: Install) -> Path:
    return install.state / "cplugs" / "huddle" / "files"


def test_two_items_that_named_one_file_each_get_their_own_copy(tmp_path: Path) -> None:
    paste = paste_in(tmp_path)
    crate = export_naming(tmp_path, [str(paste), str(paste)])
    install = with_task_folder(target_install(tmp_path, crate), tmp_path)
    receipt = run(crate, install)
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    refs = file_refs(install)
    assert len(refs) == 2 and refs[0]["item_id"] != refs[1]["item_id"] and refs[0]["path"] != refs[1]["path"]
    for ref in refs:
        assert ref["path"] == f"files/{ref['item_id']}/{NAME}"
        assert (install.state / "cplugs" / "huddle" / ref["path"]).read_bytes() == BYTES
    assert paste.read_bytes() == BYTES, "the source file is never touched"


def test_a_file_reference_resolves_under_the_importing_stores_root(tmp_path: Path) -> None:
    paste = paste_in(tmp_path)
    crate = export_naming(tmp_path, [str(paste), str(paste)])
    install = with_task_folder(target_install(tmp_path, crate), tmp_path)
    run(crate, install)
    root = files_root(install).resolve()
    for ref in file_refs(install):
        assert not Path(ref["path"]).is_absolute(), "never the source machine's absolute path"
        assert root in (install.state / "cplugs" / "huddle" / ref["path"]).resolve().parents


def test_undo_removes_the_copied_files_and_nothing_else(tmp_path: Path) -> None:
    paste = paste_in(tmp_path)
    crate = export_naming(tmp_path, [str(paste), str(paste)])
    install = with_task_folder(target_install(tmp_path, crate), tmp_path)
    hooks, import_id = RecordingHooks(), new_import_id()
    run(crate, install, hooks=hooks, import_id=import_id)
    copies = [install.state / "cplugs" / "huddle" / r["path"] for r in file_refs(install)]
    assert all(c.is_file() for c in copies)
    report = ap.recover_files(hooks.log, install.env, import_id)
    assert not any(c.exists() for c in copies) and not any(c.parent.exists() for c in copies)
    assert not report.errors and not report.kept, report
    assert paste.read_bytes() == BYTES


def test_a_failure_after_the_copies_leaves_no_file_and_no_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paste = paste_in(tmp_path)
    crate = export_naming(tmp_path, [str(paste), str(paste)])
    install = with_task_folder(target_install(tmp_path, crate), tmp_path)
    before = rows_of(install, "SELECT COUNT(*) FROM work_messages")[0][0]

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(ledger, "write_entry", boom)
    with pytest.raises(ImportFailed) as failed:
        run(crate, install)
    assert failed.value.rolled_back is True
    assert rows_of(install, "SELECT COUNT(*) FROM work_messages")[0][0] == before and file_refs(install) == []
    assert not files_root(install).exists() or not any(p.is_file() for p in files_root(install).rglob("*"))
    assert paste.read_bytes() == BYTES


def test_a_reference_whose_bytes_are_not_here_is_dropped_with_a_warning(tmp_path: Path) -> None:
    unmarked = paste_in(tmp_path, marker=False)
    crate = export_naming(tmp_path, [str(unmarked), str(tmp_path / "gone" / "pastes" / NAME)])
    install = with_task_folder(target_install(tmp_path, crate), tmp_path)
    receipt = run(crate, install)
    assert file_refs(install) == [], "no message names a file that is not there"
    assert "task_file_not_copied" in [w["code"] for w in receipt.warnings]
    texts = [r["text"] for r in rows_of(install, "SELECT text FROM work_messages WHERE item_id IN (SELECT id FROM work_items WHERE text LIKE 'item %') ORDER BY id")]
    assert texts == ["see file\n[shot.png was not on this computer]"] * 2, "the message text stays and says a file was here"
    assert not list(files_root(install).rglob(NAME)), "nothing was copied"


def test_with_no_task_manager_folder_set_every_absolute_reference_is_dropped(tmp_path: Path) -> None:
    paste = paste_in(tmp_path)
    crate = export_naming(tmp_path, [str(paste), str(paste)])
    install = target_install(tmp_path, crate)
    receipt = run(crate, install)
    assert file_refs(install) == [] and "task_file_not_copied" in [w["code"] for w in receipt.warnings]
    assert not list(files_root(install).rglob(NAME))


def test_a_file_outside_the_task_manager_folder_is_dropped(tmp_path: Path) -> None:
    paste = paste_in(tmp_path)
    crate = export_naming(tmp_path, [str(paste), str(paste)])
    install = with_task_folder(target_install(tmp_path, crate), tmp_path / "elsewhere")
    run(crate, install)
    assert file_refs(install) == [] and not list(files_root(install).rglob(NAME))
