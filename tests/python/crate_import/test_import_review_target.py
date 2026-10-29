
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from src.core.crate_import import target
from src.core.crate_import.model import ACTION_FOLLOW, B_RELOCATE_REQUIRED, MODE_SAME, Collector, ImportRequest
from src.core.crate_import.provenance import FOREIGN, OWN_VERIFIED, Provenance
from src.core.db import connect, db_path_for
from src.core.project_writes import insert_project_row
from tests.python.crate_import.install import Install, make_install

UID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _seed(install: Install, root: Path, uid: str | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path_for(install.state))) as conn:
        conn.execute("BEGIN IMMEDIATE")
        insert_project_row(conn, root=str(root), raw_path=str(root), name=root.name, uid=uid, source="user")
        conn.commit()


def _decide(install: Install, crate: target.CrateProject, prov: Provenance, request: ImportRequest) -> tuple:
    col = Collector()
    with closing(connect(db_path_for(install.state))) as conn:
        return target.decide(crate, request, prov, install.env, conn, col), col


def test_a_session_crate_follows_its_project_uid_onto_the_folder_it_has_now(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    _seed(install, install.projects / "moved-here", UID)
    crate = target.CrateProject(scope="session", uid=UID, root=str(install.projects / "was-here"), raw_path=None, name="P",
                                created_epoch=1_700_000_000, working_dirs=(str(install.projects / "was-here"),))
    decision, col = _decide(install, crate, Provenance(OWN_VERIFIED, "written_here", True), ImportRequest(mode=MODE_SAME))
    assert not col.blockers
    assert decision.action == ACTION_FOLLOW
    assert decision.root_to == str(install.projects / "moved-here")


def test_a_foreign_session_crate_never_attaches_to_a_project_outside_the_projects_folder(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    outside = tmp_path / "elsewhere" / "realproj"
    _seed(install, outside, None)
    crate = target.CrateProject(scope="session", uid=None, root=None, raw_path=None, name="S", created_epoch=1_700_000_000,
                                working_dirs=(str(outside / "src"),))
    decision, col = _decide(install, crate, Provenance(FOREIGN, "no_evidence", False), ImportRequest(mode=MODE_SAME))
    assert decision.action is None
    assert [b.code for b in col.blockers] == [B_RELOCATE_REQUIRED]


def test_a_same_path_restore_of_a_rootless_session_crate_keeps_the_working_dir(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    root = install.projects / "app"
    _seed(install, root, None)
    sub = str(root / "sub")
    crate = target.CrateProject(scope="session", uid=None, root=None, raw_path=None, name="S", created_epoch=1_700_000_000,
                                working_dirs=(sub,))
    decision, col = _decide(install, crate, Provenance(OWN_VERIFIED, "written_here", True), ImportRequest(mode=MODE_SAME))
    assert not col.blockers and decision.root_to == str(root)
    assert decision.mapping.apply(sub) in (None, sub)
