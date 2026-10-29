
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_import import apply as ap
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.db import connect, db_path_for
from src.core.project_tombstones import record_tombstone, tombstoned_roots
from src.core.session_imported_restart import DIRECTORY_MEASURED, resume_directory
from src.core.session_journal_store import empty_journal, load_journal, save_journal
from src.core.session_recreate import RECREATE, TMUX_GONE, TmuxPresence, plan_recreate
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan as build_export_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, session_request
from tests.python.crate_import.install import Install
from tests.python.crate_import.test_import_plan import export_crate, target
from tests.python.crate_import.test_import_same_path import rows_of, run
from tests.python.inventory.world import CONV_A, CONV_B, UUID_A, UUID_B, UUID_D


def touched(conn: sqlite3.Connection, root: str) -> None:
    conn.execute("UPDATE conversation_index SET working_dir = ?, files_touched_json = ? WHERE conversation_id = ?",
                 (root, json.dumps([f"{root}/src/app.py", f"{root}/README.md"]), CONV_A))


def export_with_paths(tmp: Path) -> SimpleNamespace:
    root1 = str((tmp / "w" / "proj1").resolve())
    return export_crate(tmp, hostile=lambda conn: touched(conn, root1))


def seed_journal(install: Install, root: str, other_root: str) -> None:
    journal = empty_journal()
    journal["sessions"] = {
        "a": {"session_uuid": UUID_A, "state": "live", "tmux_name": "carnivore_a", "tmux_epoch": 1, "cwd": f"{root}/sub"},
        "d": {"session_uuid": UUID_D, "state": "live", "tmux_name": "carnivore_d", "tmux_epoch": 2, "cwd": f"{root}/sub"},
    }
    journal["offer"] = {"id": "o1", "state": "open", "candidates": [{"session_uuid": UUID_D, "folder": other_root}]}
    assert save_journal(install.state, journal)


def relocated(tmp: Path, name: str = "moved-one") -> tuple:
    crate = export_with_paths(tmp)
    install = target(tmp, crate)
    old, new = crate.world.root1, str(install.projects / name)
    with closing(install.db()) as conn:
        record_tombstone(conn, old, "Proj One")
        record_tombstone(conn, new, "Proj One")
        conn.commit()
    seed_journal(install, old, crate.world.root2)
    return crate, install, new, old


def test_a_relocated_project_restores_into_the_new_root(tmp_path: Path) -> None:
    crate, install, new, old = relocated(tmp_path)
    request = ImportRequest(mode="relocate", new_root=new)
    receipt = run(crate, install, request=request)
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    assert receipt.checks["resume_unverified"] == {} and receipt.checks["resume_measured"] == 2 and receipt.checks["file_mismatch"] == []

    real_new = str(Path(new).resolve())
    folder = install.claude / "projects" / slugify_project_dir(real_new)
    source = Path(crate.world.home, "projects") / slugify_project_dir(old)
    assert folder.is_dir() and not (install.claude / "projects" / slugify_project_dir(old)).exists()
    placed = [p for p in sorted(source.rglob("*.jsonl")) if (folder / p.relative_to(source)).exists()]
    assert {p.name for p in placed} >= {f"{CONV_A}.jsonl", f"{CONV_B}.jsonl"}
    for original in placed:
        assert (folder / original.relative_to(source)).read_bytes() == original.read_bytes()

    project = rows_of(install, "SELECT * FROM projects")[0]
    assert (project["uid"], project["root"]) == ("project-uid-1", real_new)
    sessions = {r["session_uuid"]: r for r in rows_of(install, "SELECT * FROM sessions")}
    assert set(sessions) == {UUID_A, UUID_B}
    assert {r["working_dir"] for r in sessions.values()} == {real_new}
    index = rows_of(install, "SELECT working_dir, files_touched_json FROM conversation_index WHERE conversation_id = ?", CONV_A)[0]
    assert index["working_dir"] == real_new
    assert json.loads(index["files_touched_json"]) == [f"{real_new}/src/app.py", f"{real_new}/README.md"]

    with closing(connect(db_path_for(install.state))) as conn:
        assert real_new not in tombstoned_roots(conn) and new not in tombstoned_roots(conn)
        assert old in tombstoned_roots(conn)

    journal = load_journal(install.state).journal
    assert journal["sessions"]["a"]["cwd"] == f"{real_new}/sub"
    assert journal["sessions"]["d"]["cwd"] == f"{old}/sub"
    assert journal["offer"]["candidates"] == [{"session_uuid": UUID_D, "folder": crate.world.root2}]

    for row in sessions.values():
        found = resume_directory(row["working_dir"], row["claude_session_uuid"], corpus_root=install.claude / "projects")
        assert found.outcome == DIRECTORY_MEASURED
        plan = plan_recreate(dict(row), row_read_ok=True, presence=TmuxPresence(TMUX_GONE), choice_verdict="accepted",
                             choice_command=f"claude --resume {row['claude_session_uuid']}", directory=found)
        assert plan.kind == RECREATE, plan


def test_running_it_again_into_the_new_root_writes_nothing(tmp_path: Path) -> None:
    crate, install, new, _old = relocated(tmp_path)
    request = ImportRequest(mode="relocate", new_root=new)
    run(crate, install, request=request)
    before = (rows_of(install, "SELECT * FROM sessions"), load_journal(install.state).journal)
    receipt = run(crate, install, request=request)
    assert receipt.state == "noop" and receipt.files["written"] == 0
    assert (rows_of(install, "SELECT * FROM sessions"), load_journal(install.state).journal) == before


def test_a_project_crate_follows_its_uid_to_the_root_it_has_here(tmp_path: Path) -> None:
    crate = export_with_paths(tmp_path)
    install = target(tmp_path, crate)
    here = str((install.projects / "already-here").resolve())
    Path(here).mkdir()
    with closing(install.db()) as conn:
        conn.execute("INSERT INTO projects (uid, display_name, root, raw_path, source, created_at, updated_at) "
                     "VALUES ('project-uid-1', 'Renamed Here', ?, ?, 'user', 'now', 'now')", (here, here))
        conn.commit()
    receipt = run(crate, install)
    assert receipt.project["action"] == "follow_uid" and receipt.project["root"] == here
    project = rows_of(install, "SELECT id, display_name, root FROM projects")
    assert [(p["display_name"], p["root"]) for p in project] == [("Renamed Here", here)]
    sessions = rows_of(install, "SELECT project_id, working_dir FROM sessions")
    assert len(sessions) == 2 and {(s["project_id"], s["working_dir"]) for s in sessions} == {(project[0]["id"], here)}
    assert (install.claude / "projects" / slugify_project_dir(here)).is_dir()
    assert receipt.checks["resume_measured"] == 2 and receipt.checks["resume_unverified"] == {}


def session_crate(tmp: Path) -> SimpleNamespace:
    (tmp / "w").mkdir()
    from tests.python.cplugs.crate.crate_world import make_world

    world = make_world(tmp / "w")
    env = env_for(world)
    plan = build_export_plan(env, session_request(UUID_A))
    assert plan.ok, plan.blockers
    result = run_export(env, plan, JobHandle("s3"))
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=world, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id)


def test_a_session_crate_names_its_project(tmp_path: Path) -> None:
    crate = session_crate(tmp_path)
    with cf.open_crate(crate.path) as reader:
        scope: Dict[str, Any] = reader.manifest.scope
    assert (scope["kind"], scope["project_uid"], scope["project_name"], scope["project_root"]) == (
        "session", "project-uid-1", "Proj One", crate.world.root1)
    install = target(tmp_path, crate)
    new = str(install.projects / "from-a-session")
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(mode="relocate", new_root=new), crate_sha256=crate.sha256, encrypted=False)
    assert plan["ok"], plan["blockers"]
    assert plan["project"]["action"] == "create" and plan["project"]["uid"] == "project-uid-1"
    receipt = run(crate, install, request=ImportRequest(mode="relocate", new_root=new))
    assert receipt.checks["resume_measured"] == 1 and receipt.checks["resume_unverified"] == {}
    rows: List[sqlite3.Row] = rows_of(install, "SELECT s.session_uuid, s.working_dir, p.root FROM sessions s JOIN projects p ON p.id = s.project_id")
    assert [(r["session_uuid"], r["working_dir"], r["root"]) for r in rows] == [(UUID_A, str(Path(new).resolve()), str(Path(new).resolve()))]
