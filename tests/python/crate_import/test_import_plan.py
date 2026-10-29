
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import ImportRequest
from src.core.crate_import.plan import build_plan as plan_import
from src.core.db import connect, db_path_for, set_meta
from src.core.exports.store import crate_written_key
from src.core.project_move.plan import PaneListing
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request
from tests.python.crate_import.install import Install, make_install
from tests.python.session_purge.purge_world import insert
from tests.python.inventory.world import EPOCH_A, TMUX_A, UUID_A

FIXTURES_V11 = Path(__file__).resolve().parents[2] / "fixtures" / "crate" / "v1.1"


def export_crate(tmp: Path, hostile: Optional[Callable[[sqlite3.Connection], None]] = None) -> SimpleNamespace:
    (tmp / "w").mkdir()
    world = make_world(tmp / "w")
    if hostile is not None:
        with closing(sqlite3.connect(world.main)) as conn:
            hostile(conn)
            conn.commit()
    env = env_for(world)
    plan = build_plan(env, project_request(world))
    assert plan.ok, plan.blockers
    result = run_export(env, plan, JobHandle("s1"))
    with cf.open_crate(result.path) as reader:
        install_id = reader.manifest.source["install_id"]
    return SimpleNamespace(world=world, path=result.path, sha256=result.sha256, install_id=install_id, bundle_id=result.bundle_id)


def target(tmp: Path, crate: SimpleNamespace, *, mark: bool = True, **kw: Any) -> Install:
    (tmp / "t").mkdir(exist_ok=True)
    install = make_install(tmp / "t", install_id=crate.install_id, **kw)
    if mark:
        with closing(install.db()) as conn:
            set_meta(conn, crate_written_key(crate.bundle_id), crate.sha256)
            conn.commit()
    return install


def world_env(crate: SimpleNamespace, **kw: Any) -> ImportEnv:
    world = crate.world
    projects = Path(world.tmp) / "projects"
    projects.mkdir(exist_ok=True)
    values = dict(state=Path(world.state), projects_dir=str(projects), claude_homes=(Path(world.home),),
                  codex_home=Path(world.codex), install_id=crate.install_id, panes=lambda: PaneListing(True),
                  writers=lambda: (), free_bytes=lambda path: 10**12)
    values.update(kw)
    return ImportEnv(**values)


def plan_of(crate: SimpleNamespace, env: ImportEnv, request: Optional[ImportRequest] = None) -> Dict[str, Any]:
    with cf.open_crate(crate.path) as reader:
        return plan_import(reader, env, request or ImportRequest(), crate_sha256=crate.sha256, encrypted=False)


def codes(items: List[Dict[str, str]]) -> List[str]:
    return [i["code"] for i in items]


_UNHASHED = ("-wal", "-shm", "vault-summaries.z")


def tree_hash(*roots: Path) -> str:
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted(p for p in Path(root).rglob("*") if p.is_file() and not p.name.endswith(_UNHASHED)):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()



def test_same_path_plan_on_an_empty_install(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    plan = plan_of(crate, install.env)
    assert plan["ok"] is True, plan["blockers"]
    assert plan["provenance"] == "own_verified" and plan["provenance_reason"] == "written_here"
    assert plan["project"]["action"] == "create" and plan["project"]["root_to"] == plan["project"]["root_from"]
    assert plan["project"]["uid"] == "project-uid-1"
    assert plan["fingerprint"] and len(plan["fingerprint"]) == 64
    sessions = plan["rows"]["cloude.db.sessions"]
    assert sessions["insert"] == 2 and sessions["present"] == 0
    assert {c["class"] for c in plan["conversations"]} == {"write"} and all("reason" not in c for c in plan["conversations"])
    assert not any(n["what"].startswith("files:orphan_transcript") for n in plan["not_restored"])
    assert all(e["to"] == e["from"] for e in plan["enc"]) and plan["enc"]
    assert plan["files"]["count"] > 0 and plan["files"]["bytes"] > 0
    assert plan["rows"]["cloude.db.pack_migrations"]["reason"] == "machine"
    assert "blockers" in plan and plan["blockers"] == []


def test_a_project_already_at_the_root_is_attached(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    root = crate.world.root1
    with closing(install.db()) as conn:
        insert(conn, "projects", uid="other-uid", display_name="Mine", root=root, raw_path=root, source="user", created_at="now", updated_at="now")
        conn.commit()
    plan = plan_of(crate, install.env)
    assert plan["ok"] is True, plan["blockers"]
    assert plan["project"]["action"] == "attach" and plan["project"]["name"] == "Mine"


def test_a_relocated_plan_names_the_new_folder_name(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    new_root = str((install.projects / "moved").resolve())
    plan = plan_of(crate, install.env, ImportRequest(mode="relocate", new_root=new_root))
    assert plan["ok"] is True, plan["blockers"]
    assert plan["project"]["root_to"] == new_root
    assert any(m["to"] == new_root for m in plan["mapping"])
    moved = [e for e in plan["enc"] if e["to"] != e["from"]]
    assert moved, "the folder names of a relocated import are the new launch folder's"
    assert {e["to"] for e in moved} == {slugify_project_dir(new_root)}, plan["enc"]



def test_a_crate_that_claims_this_computer_without_the_mark_is_foreign(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate, mark=False)
    plan = plan_of(crate, install.env)
    assert plan["provenance"] == "foreign" and plan["provenance_reason"] == "claims_this_computer_not_proven"
    assert "claims_this_computer" in codes(plan["warnings"])
    assert "relocate_required" in codes(plan["blockers"])
    assert plan["ok"] is False and plan["fingerprint"] == ""
    assert plan["project"]["suggested_root"].startswith(str(install.projects))


def test_another_computers_crate_is_foreign_and_the_owner_tick_promotes_only_a_claiming_crate(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    other = target(tmp_path, crate, mark=False)
    stranger = ImportEnv(**{**other.env.__dict__, "install_id": "22222222-2222-4222-8222-222222222222"})
    assert plan_of(crate, stranger)["provenance_reason"] == "other_computer"
    assert plan_of(crate, stranger, ImportRequest(made_here=True))["provenance"] == "foreign"
    ticked = plan_of(crate, other.env, ImportRequest(made_here=True))
    assert ticked["provenance"] == "own_verified" and ticked["provenance_reason"] == "owner_attested"


def test_a_different_file_with_the_same_bundle_id_is_foreign(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    with cf.open_crate(crate.path) as reader:
        plan = plan_import(reader, install.env, ImportRequest(), crate_sha256="0" * 64, encrypted=False)
    assert plan["provenance"] == "foreign" and plan["provenance_reason"] == "mark_differs"


def test_a_foreign_crate_into_the_projects_folder_plans_and_resets_launch_columns(tmp_path: Path) -> None:
    def hostile(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE sessions SET launch_record = '{\"argv\": [\"claude\", \"--dangerously-skip-permissions\"]}', "
                     "agent_type = 'claude-skip-permissions' "
                     "WHERE session_uuid = ?", (UUID_A,))

    crate = export_crate(tmp_path, hostile)
    install = target(tmp_path, crate, mark=False)
    new_root = str((install.projects / "restored").resolve())
    plan = plan_of(crate, install.env, ImportRequest(mode="relocate", new_root=new_root))
    assert plan["ok"] is True, plan["blockers"]
    assert plan["provenance"] == "foreign"
    assert plan["dropped"]["cloude.db.sessions.launch_record"] == "foreign_launch"
    from src.core.crate_import import validate
    from src.core.crate_import.provenance import Provenance
    from src.core.project_move.paths import PathMapping

    foreign = Provenance("foreign", "other_computer", False)
    shape_args = dict(shape=None, secret_columns=(), path_columns=(), mapping=PathMapping([]), provenance=foreign)
    row = validate.sanitize_row("sessions", {"session_uuid": "s-0001-aaaa", "host_key": "local", "agent_type": "claude-skip-permissions",
                                             "launch_record": "{}", "model": "x; rm -rf /"}, **shape_args).row
    assert row["host_key"] == "local" and row["agent_type"] == "claude" and "launch_record" not in row and row["model"] is None
    assert validate.sanitize_row("sessions", {"session_uuid": "s-0001-aaaa", "host_key": "peer:evil"}, **shape_args).skipped == "remote_session"
    assert validate.sanitize_row("sessions", {"session_uuid": "s-0001-aaaa", "companion_of": 3}, **shape_args).skipped == "companion_session"


def test_a_conversation_id_that_is_not_safe_blocks(tmp_path: Path) -> None:
    crate = export_crate(tmp_path, lambda c: c.execute("UPDATE sessions SET claude_session_uuid = '../../etc/x' WHERE session_uuid = ?", (UUID_A,)))
    plan = plan_of(crate, target(tmp_path, crate).env)
    assert "bad_identifier" in codes(plan["blockers"]) and plan["ok"] is False


def test_a_working_dir_outside_the_crate_scope_blocks(tmp_path: Path) -> None:
    crate = export_crate(tmp_path, lambda c: c.execute("UPDATE sessions SET working_dir = '/etc' WHERE session_uuid = ?", (UUID_A,)))
    plan = plan_of(crate, target(tmp_path, crate).env)
    assert "path_outside_scope" in codes(plan["blockers"])


def _foreign_install_at_home(tmp_path: Path, crate: SimpleNamespace, home: Path) -> Install:
    install = target(tmp_path, crate, mark=False)
    return Install(replace(install.env, home=home), install.state, install.projects, install.claude, install.codex)


def test_a_foreign_crate_into_its_original_folder_under_home_plans_ok(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = _foreign_install_at_home(tmp_path, crate, tmp_path)
    assert crate.world.root1.startswith(str(tmp_path)) and not str(crate.world.root1).startswith(str(install.projects))
    plan = plan_of(crate, install.env)
    assert plan["provenance"] == "foreign"
    assert plan["ok"] is True, plan["blockers"]
    assert plan["project"]["root_to"] == crate.world.root1 and plan["project"]["root_from"] == crate.world.root1
    relocated = plan_of(crate, install.env, ImportRequest(mode="relocate", new_root=crate.world.root1))
    assert relocated["ok"] is True, relocated["blockers"]


def test_a_foreign_crate_outside_home_or_in_a_protected_place_stays_blocked(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    home = tmp_path / "somebody"
    (home / "Library" / "Keychains").mkdir(parents=True)
    (home / "Library" / "Mobile Documents").mkdir(parents=True)
    (home / ".claude").mkdir()
    install = _foreign_install_at_home(tmp_path, crate, home)
    assert plan_of(crate, install.env)["ok"] is False and "relocate_required" in codes(plan_of(crate, install.env)["blockers"])
    for refused in (home / "Library" / "Keychains" / "x", home / "Library" / "Application Support" / "x", home / ".claude" / "x", home / ".ssh" / "x", home):
        plan = plan_of(crate, install.env, ImportRequest(mode="relocate", new_root=str(refused)))
        assert plan["ok"] is False, refused
    iCloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "proj"
    iCloud.parent.mkdir(parents=True)
    assert plan_of(crate, install.env, ImportRequest(mode="relocate", new_root=str(iCloud)))["ok"] is True


def test_a_root_in_a_launch_agents_folder_is_refused(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate, mark=False)
    bad = str(Path.home() / "Library" / "LaunchAgents" / "x")
    plan = plan_of(crate, install.env, ImportRequest(mode="relocate", new_root=bad))
    assert plan["ok"] is False and {"root_refused", "relocate_required"} & set(codes(plan["blockers"]))
    own = target(tmp_path / "again", crate) if (tmp_path / "again").mkdir() is None else None
    refused = plan_of(crate, own.env, ImportRequest(mode="relocate", new_root=bad))
    assert "root_refused" in codes(refused["blockers"]) and refused["ok"] is False


def test_a_secret_column_is_dropped_and_secret_and_grant_tables_are_never_written(tmp_path: Path) -> None:
    from src.core.crate_import import validate
    from src.core.crate_import.provenance import Provenance
    from src.core.project_move.paths import PathMapping

    verdict = validate.sanitize_row("work_item_waits", {"item_id": 1, "token_hash": "abc"}, shape=None, secret_columns=("token_hash",),
                                    path_columns=(), mapping=PathMapping([]), provenance=Provenance("foreign", "other_computer", False))
    assert verdict.dropped == {"token_hash": "secret"} and "token_hash" not in verdict.row
    crate = export_crate(tmp_path)
    plan = plan_of(crate, target(tmp_path, crate).env)
    assert plan["rows"]["cloude.db.work_item_waits"]["reason"] == "secret"
    assert plan["rows"]["cloude.db.spectator_links"]["reason"] == "grant"
    assert plan["rows"]["cloude.db.work_item_waits"]["insert"] == 0 and plan["rows"]["cloude.db.spectator_links"]["insert"] == 0



def test_a_live_pane_blocks(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    live = PaneListing(True, ((TMUX_A, EPOCH_A, crate.world.root1),))
    plan = plan_of(crate, world_env(crate, panes=lambda: live))
    assert "session_live" in codes(plan["blockers"]) and plan["ok"] is False


def test_an_unanswered_pane_listing_blocks(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    plan = plan_of(crate, world_env(crate, panes=lambda: PaneListing(False, reason="tmux did not answer")))
    assert "panes_unknown" in codes(plan["blockers"])


def test_an_unmeasured_process_table_blocks(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    plan = plan_of(crate, world_env(crate, writers=lambda: None))
    assert "writers_unmeasured" in codes(plan["blockers"])


def test_an_open_reopen_offer_naming_a_crate_session_blocks(tmp_path: Path) -> None:
    from src.core import session_journal_store as store

    crate = export_crate(tmp_path)
    journal = store.empty_journal()
    journal["offer"] = {"id": "o1", "entries": [{"session_uuid": UUID_A}]}
    assert store.save_journal(Path(crate.world.state), journal)
    plan = plan_of(crate, world_env(crate))
    assert "offer_names_session" in codes(plan["blockers"])



def test_a_new_destination_file_changes_the_fingerprint(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    first = plan_of(crate, install.env)
    assert plan_of(crate, install.env)["fingerprint"] == first["fingerprint"]
    folder = next(iter(install.claude.joinpath("projects").iterdir()), None)
    assert folder is None
    enc = first["enc"][0]["to"]
    (install.claude / "projects" / enc).mkdir()
    (install.claude / "projects" / enc / "appeared.jsonl").write_text("x\n")
    (install.claude / "projects" / enc / (next(c["id"] for c in first["conversations"]) + ".jsonl")).write_text("different\n")
    assert plan_of(crate, install.env)["fingerprint"] != first["fingerprint"]


def test_the_plan_writes_nothing(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    before = tree_hash(install.state, install.claude, install.codex, install.projects)
    plan_of(crate, install.env)
    plan_of(crate, install.env, ImportRequest(mode="relocate", new_root=str(install.projects / "m")))
    assert tree_hash(install.state, install.claude, install.codex, install.projects) == before



@pytest.mark.parametrize("name", ["project-own.crate", "session-own.crate"])
def test_every_v11_golden_crate_plans(tmp_path: Path, name: str) -> None:
    path = FIXTURES_V11 / name
    install = make_install(tmp_path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with cf.open_crate(path) as reader:
        plan = plan_import(reader, install.env, ImportRequest(), crate_sha256=sha, encrypted=False)
    assert plan["crate"]["variant"] == "own" and plan["provenance"] == "foreign"
    assert "version" in plan and plan["blockers"], "a foreign crate into an empty install needs a folder or a project choice"
    assert set(codes(plan["blockers"])) <= {"relocate_required", "project_choice_needed", "root_refused"}
