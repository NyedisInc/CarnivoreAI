
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from src.core.crate_import import idmap, ledger
from src.core.crate_import.model import ImportRequest
from src.core.db import connect, db_path_for
from tests.python.crate_import.test_import_same_path import rows_of, run
from tests.python.crate_import.test_import_work_side import export_world, items, target_install


def test_items_deleted_since_an_earlier_import_are_restored_again(tmp_path: Path) -> None:
    crate = export_world(tmp_path)
    install = target_install(tmp_path, crate)
    first = run(crate, install)
    assert first.state in ("done", "done_with_warnings"), first.warnings
    project = rows_of(install, "SELECT id FROM projects WHERE uid = 'project-uid-1'")[0]["id"]
    live = [r["id"] for r in items(install) if r["list_key"] == str(project)]
    assert len(live) == 3
    with closing(install.db()) as conn:
        conn.execute("UPDATE work_items SET deleted = 1 WHERE list_key = ?", (str(project),))
        conn.commit()
    second = run(crate, install)
    assert second.state in ("done", "done_with_warnings"), "the missing items are real work, not a noop"
    again = [r for r in items(install) if r["list_key"] == str(project)]
    assert len(again) == 3 and not {r["id"] for r in again} & set(live)


def test_a_session_of_the_crates_own_project_follows_this_imports_project_not_an_earlier_map(tmp_path: Path) -> None:
    crate = export_world(tmp_path)
    install = target_install(tmp_path, crate)
    with closing(connect(db_path_for(install.state))) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ledger.write_entry(conn, "imp-20260101T000000Z-aaaaaaaa", {"source_install": crate.install_id, "bundle_id": "old", "crate_sha256": "0" * 64,
                                                                    "phase": "done", "key_map": {idmap.PROJECTS: {str(crate.world.p1): 99}}, "created": {}})
        conn.commit()
    run(crate, install, request=ImportRequest())
    project = rows_of(install, "SELECT id FROM projects WHERE uid = 'project-uid-1'")[0]["id"]
    assert project != 99
    assert {r["project_id"] for r in rows_of(install, "SELECT project_id FROM sessions")} == {project}
