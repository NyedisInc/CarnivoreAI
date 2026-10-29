
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.crate_import import apply as ap
from src.core.crate_import import hooks as hk
from src.core.crate_import import ledger
from src.core.crate_import.model import ImportFailed, ImportRefused, ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.db import connect, db_path_for
from src.core.project_move.apply import one_move_at_a_time
from src.core.project_move.plan import PaneListing
from src.core.project_tombstones import record_tombstone, tombstoned_roots
from src.core.session_imported_restart import DIRECTORY_MEASURED, resume_directory
from src.core.session_restore_offer import offer_candidates
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.install import Install
from tests.python.crate_import.test_import_plan import export_crate, target, tree_hash
from tests.python.inventory.world import CONV_A, CONV_B, TMUX_A, UUID_A, UUID_B

REPO = Path(__file__).resolve().parents[3]


class SimulatedCrash(BaseException):
    pass


class Faults(hk.ApplyHooks):

    def __init__(self, at: Optional[str] = None, error: Optional[BaseException] = None) -> None:
        self.at, self.error, self.log, self.phases = at, error, [], []

    def phase(self, name: str, total: int = 0, files: int = 0) -> None:
        self.phases.append(name)

    def undo(self, entry: Dict[str, Any]) -> None:
        self.log.append(entry)

    def checkpoint(self, name: str) -> None:
        if name == self.at and self.error is not None:
            raise self.error


def dump(install: Install) -> Dict[str, List[tuple]]:
    out: Dict[str, List[tuple]] = {}
    with closing(sqlite3.connect(f"file:{db_path_for(install.state)}?mode=ro", uri=True)) as conn:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"):
            try:
                out[name] = sorted(conn.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)
            except sqlite3.Error:
                continue
    return out


def world(install: Install) -> tuple:
    return dump(install), tree_hash(install.claude, install.codex)


def seeded(tmp: Path, **kw: Any) -> tuple:
    crate = export_crate(tmp)
    install = target(tmp, crate, **kw)
    with closing(install.db()) as conn:
        record_tombstone(conn, crate.world.root1, "Proj One")
        conn.commit()
    return crate, install


def run(crate: SimpleNamespace, install: Install, hooks: Optional[hk.ApplyHooks] = None, request: Optional[ImportRequest] = None,
        import_id: Optional[str] = None) -> ap.ImportReceipt:
    request = request or ImportRequest()
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
        assert plan["ok"], plan["blockers"]
        return ap.apply_import(reader, install.env, request, crate_sha256=crate.sha256, fingerprint=plan["fingerprint"],
                               import_id=import_id or new_import_id(), hooks=hooks)


def rows_of(install: Install, sql: str, *args: Any) -> List[sqlite3.Row]:
    with closing(connect(db_path_for(install.state), create=False)) as conn:
        return conn.execute(sql, args).fetchall()



def test_a_deleted_project_comes_back_at_its_own_root_with_its_sessions_asleep(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    root = crate.world.root1
    assert root in tombstoned_roots(connect(db_path_for(install.state)))
    receipt = run(crate, install)
    assert receipt.state in ("done", "done_with_warnings") and receipt.checks["file_mismatch"] == []
    assert receipt.checks["resume_unverified"] == {} and receipt.checks["resume_measured"] == 2

    placed = 0
    for source in sorted(Path(crate.world.home, "projects").rglob("*.jsonl")):
        mine = install.claude / "projects" / source.relative_to(Path(crate.world.home, "projects"))
        if mine.exists():
            placed += 1
            assert mine.read_bytes() == source.read_bytes(), mine
    assert placed >= 2

    project = rows_of(install, "SELECT * FROM projects")[0]
    assert (project["uid"], project["display_name"], project["root"]) == ("project-uid-1", "Proj One", root)
    with closing(connect(db_path_for(install.state))) as conn:
        assert root not in tombstoned_roots(conn)

    sessions = {r["session_uuid"]: r for r in rows_of(install, "SELECT * FROM sessions")}
    assert set(sessions) == {UUID_A, UUID_B}
    with closing(sqlite3.connect(crate.world.main)) as src:
        src.row_factory = sqlite3.Row
        for uuid, row in sessions.items():
            original = src.execute("SELECT * FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()
            for column in ("title", "claude_session_uuid", "working_dir", "created_at"):
                assert row[column] == original[column], (uuid, column)
            assert row["project_id"] == project["id"]
            assert (row["lifecycle"], row["lifecycle_source"]) == ("stopped", "import")
            assert row["tmux_name"] is None and row["tmux_created_epoch"] is None and row["tmux_session_id"] is None
            got = resume_directory(row["working_dir"], row["claude_session_uuid"], corpus_root=install.claude / "projects")
            assert got.outcome == DIRECTORY_MEASURED, (uuid, got)
    assert sessions[UUID_B]["parent_session_id"] == sessions[UUID_A]["id"]

    journal = {"sessions": {"x": {"session_uuid": UUID_A, "state": "live", "tmux_name": TMUX_A, "tmux_epoch": 1}}, "declined": {}}
    with_identity = [dict(r) for r in rows_of(install, "SELECT * FROM sessions WHERE tmux_name IS NOT NULL")]
    assert offer_candidates(journal, with_identity, live_instances=set()) == []

    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
    assert plan["project"]["action"] == "attach" and plan["rows"]["cloude.db.sessions"]["present"] == 2
    entry = ledger.read_entry(connect(db_path_for(install.state)), receipt.import_id)
    assert entry["phase"] in ("done", "done_with_warnings") and set(entry["key_map"]["cloude.db.sessions"].values()) == {s["id"] for s in sessions.values()}
    assert receipt.rows["cloude.db.sessions"]["inserted"] == 2
    for table in ("session_notes", "conversation_index", "lineage_nodes", "session_groups", "layouts"):
        assert rows_of(install, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] == receipt.rows[f"cloude.db.{table}"]["inserted"], table
    assert {c["id"] for c in receipt.conversations if c["class"] == "write"} >= {CONV_A, CONV_B}


def test_restoring_again_writes_nothing(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    run(crate, install)
    before = world(install)
    receipt = run(crate, install)
    assert receipt.state == "noop" and receipt.files["written"] == 0
    assert all(c["inserted"] == 0 for c in receipt.rows.values())
    assert world(install) == before
    assert len([k for k in dump(install)["meta"] if str(k[0]).startswith("crate_import:")]) == 1



@pytest.mark.parametrize("at", [hk.CP_AFTER_FILES, hk.CP_BEFORE_COMMIT])
def test_a_fault_after_the_files_leaves_the_world_identical(tmp_path: Path, at: str) -> None:
    crate, install = seeded(tmp_path)
    before = world(install)
    hooks = Faults(at, RuntimeError("injected"))
    with pytest.raises(RuntimeError, match="injected"):
        run(crate, install, hooks)
    assert any(e["op"] == "file" for e in hooks.log), "the files phase did place files before the fault"
    assert world(install) == before


def test_a_database_error_rolls_the_rows_and_the_files_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.crate_import import rows_write

    crate, install = seeded(tmp_path)
    before = world(install)

    def boom(*_a: Any, **_k: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(rows_write, "write_generic", boom)
    with pytest.raises(ImportFailed) as caught:
        run(crate, install)
    assert caught.value.code == "database_failed" and caught.value.rolled_back is True
    assert world(install) == before


def test_a_crash_before_the_commit_is_undone_from_the_persisted_log(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    before = world(install)
    hooks = Faults(hk.CP_AFTER_FILES, SimulatedCrash())
    with pytest.raises(SimulatedCrash):
        run(crate, install, hooks)
    assert world(install) != before
    first = ap.recover_files(hooks.log, install.env)
    assert first.removed and not first.errors
    assert world(install) == before
    assert ap.recover_files(hooks.log, install.env).removed == []


def test_an_undo_never_deletes_a_file_someone_else_changed(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    hooks = Faults(hk.CP_AFTER_FILES, SimulatedCrash())
    with pytest.raises(SimulatedCrash):
        run(crate, install, hooks)
    victim = Path(next(e["path"] for e in hooks.log if e["op"] == "file"))
    victim.write_bytes(victim.read_bytes() + b"mine\n")
    report = ap.recover_files(hooks.log, install.env)
    assert str(victim) in report.kept and victim.exists()
    outside = [{"op": "file", "path": str(tmp_path / "elsewhere.txt"), "sha256": "0" * 64, "length": 1}]
    (tmp_path / "elsewhere.txt").write_text("x")
    assert ap.recover_files(outside, install.env).kept == [str(tmp_path / "elsewhere.txt")]


def test_a_crash_after_the_commit_finishes_to_the_same_end_state_as_a_clean_run(tmp_path: Path) -> None:
    (tmp_path / "clean").mkdir()
    clean_crate, clean = seeded(tmp_path / "clean")
    run(clean_crate, clean)
    (tmp_path / "crash").mkdir()
    crate, install = seeded(tmp_path / "crash")
    import_id = new_import_id()
    with pytest.raises(SimulatedCrash):
        run(crate, install, Faults(hk.CP_AFTER_ROWS, SimulatedCrash()), import_id=import_id)
    assert ledger.read_entry(connect(db_path_for(install.state)), import_id)["phase"] == "rows_committed"
    with cf.open_crate(crate.path) as reader:
        receipt = ap.finish_import(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, import_id=import_id)
    assert receipt.state in ("done", "done_with_warnings") and receipt.checks["resume_measured"] == 2
    assert ledger.read_entry(connect(db_path_for(install.state)), import_id)["phase"] in ("done", "done_with_warnings")
    ours, theirs = dump(install), dump(clean)
    for table in ("projects", "sessions", "conversation_index", "session_notes", "lineage_nodes", "lineage_edges", "layouts", "companies",
                  "conversation_milestones"):
        assert len(ours[table]) == len(theirs[table]) and len(ours[table]) > 0 or table in ("lineage_edges", "layouts"), table
    assert sorted(r["session_uuid"] for r in rows_of(install, "SELECT session_uuid FROM sessions")) == \
        sorted(r["session_uuid"] for r in rows_of(clean, "SELECT session_uuid FROM sessions"))
    assert sorted(r["lifecycle"] for r in rows_of(install, "SELECT lifecycle FROM sessions")) == ["stopped", "stopped"]
    with pytest.raises(ImportRefused) as missing:
        with cf.open_crate(crate.path) as reader:
            ap.finish_import(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, import_id=new_import_id())
    assert missing.value.code == "no_such_import"



def test_a_stale_fingerprint_is_plan_changed_with_the_fresh_plan_and_nothing_is_written(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    before = world(install)
    with cf.open_crate(crate.path) as reader, pytest.raises(ImportRefused) as caught:
        ap.apply_import(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, fingerprint="0" * 64, import_id=new_import_id())
    assert caught.value.code == "plan_changed" and caught.value.plan["fingerprint"] and caught.value.plan["ok"]
    assert world(install) == before


def test_a_blocked_plan_and_a_live_session_write_nothing(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    before = world(install)
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
        install.env = type(install.env)(**{**install.env.__dict__, "panes": lambda: PaneListing(False, reason="gone")})
        with pytest.raises(ImportRefused) as caught:
            ap.apply_import(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, fingerprint=plan["fingerprint"], import_id=new_import_id())
    assert caught.value.code in ("blocked", "plan_changed") and caught.value.plan is not None
    assert world(install) == before


def test_a_move_in_progress_makes_the_restore_busy(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    before = world(install)
    with one_move_at_a_time(), pytest.raises(ImportRefused) as caught:
        run(crate, install)
    assert caught.value.code == "busy"
    assert world(install) == before



def test_only_the_ledger_names_the_meta_keys() -> None:
    needle = "crate_import" + ":"
    offenders = []
    for path in sorted((REPO / "src").rglob("*.py")):
        if path.name == "ledger.py" and path.parent.name == "crate_import":
            continue
        if re.search(r"""["']""" + needle, path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_a_foreign_crate_restores_into_its_original_folder_under_home(tmp_path: Path) -> None:
    from dataclasses import replace

    crate = export_crate(tmp_path)
    base = target(tmp_path, crate, mark=False)
    install = Install(replace(base.env, home=tmp_path), base.state, base.projects, base.claude, base.codex)
    receipt = run(crate, install)
    assert receipt.state in ("done", "done_with_warnings")
    assert rows_of(install, "SELECT root FROM projects")[0]["root"] == crate.world.root1
    assert not str(crate.world.root1).startswith(str(install.projects))
    assert rows_of(install, "SELECT COUNT(*) AS n FROM sessions")[0]["n"] >= 2
