
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.crate_import import ledger, undo_import
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.undo_import import UndoRefused
from src.core.db import connect, db_path_for
from src.core.deepsearch import fallback_hook as fb
from src.core.project_tombstones import tombstoned_roots
from src.cplugs.save.fallback import BackupTranscripts
from tests.python.crate_import import test_import_folder_backups as boards_rig
from tests.python.crate_import import test_import_project_files as files_rig
from tests.python.crate_import.test_import_plan import tree_hash
from tests.python.crate_import.test_import_same_path import run, seeded
from tests.python.crate_import.test_import_undo_post_commit import RecordingHooks

_LEDGER_KEYS = (ledger.LEDGER_PREFIX, ledger.UNDO_PREFIX)


def database_rows(path: Path) -> Dict[str, List[tuple]]:
    out: Dict[str, List[tuple]] = {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"):
            try:
                rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
            except sqlite3.Error:
                continue
            if name == "meta":
                rows = [r for r in rows if not str(r[0]).startswith(_LEDGER_KEYS)]
            out[name] = sorted(rows, key=repr)
    return out


def listing(*roots: Path) -> List[str]:
    skip = ("-wal", "-shm", "vault-summaries.z")
    return sorted(f"{p}:{p.stat().st_size if p.is_file() else 'dir'}" for r in roots for p in Path(r).rglob("*") if not p.name.endswith(skip))


def snapshot(install: Any, *extra: Path) -> Dict[str, Any]:
    dbs = {str(p.relative_to(install.state)): database_rows(p) for p in sorted(Path(install.state).rglob("*.db"))}
    return {"dbs": dbs, "files": tree_hash(install.claude, install.codex, install.projects, *extra), "listing": listing(install.claude, install.codex, install.projects, *extra)}


def same(now: Dict[str, Any], before: Dict[str, Any]) -> None:
    assert set(now["listing"]) ^ set(before["listing"]) == set(), sorted(set(now["listing"]) ^ set(before["listing"]))
    assert {t for d in now["dbs"] for t in now["dbs"][d] if now["dbs"][d][t] != before["dbs"].get(d, {}).get(t)} == set()
    assert now == before


def undo_it(install: Any, import_id: str, hooks: RecordingHooks, vault: Any = None) -> undo_import.UndoReport:
    fb.register("undo-test-target", BackupTranscripts(vault=lambda: vault)) if vault is not None else None
    try:
        plan = undo_import.plan_undo(install.env, import_id, hooks.log)
        assert plan.ok, plan.blockers
        return undo_import.run_undo(install.env, import_id, hooks.log)
    finally:
        if vault is not None:
            fb.unregister("undo-test-target")


def phase_of(install: Any, import_id: str) -> str:
    with closing(connect(db_path_for(install.state), create=False)) as conn:
        return str((ledger.read_entry(conn, import_id) or {}).get("phase"))


def test_same_path_undo_returns_rows_files_orphan_and_tombstone_to_the_snapshot(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    before = snapshot(install)
    hooks, import_id = RecordingHooks(), new_import_id()
    receipt = run(crate, install, hooks=hooks, import_id=import_id)
    assert receipt.state in ("done", "done_with_warnings") and snapshot(install) != before
    with closing(connect(db_path_for(install.state))) as conn:
        assert crate.world.root1 not in tombstoned_roots(conn), "the import cleared the tombstone"

    report = undo_it(install, import_id, hooks)

    assert report.rows["deleted"] > 0 and report.rows["restored"] >= 1, report.as_json()
    assert snapshot(install) == before, "rows, files, orphan transcript and tombstone are exactly as before the import"
    with closing(connect(db_path_for(install.state))) as conn:
        assert crate.world.root1 in tombstoned_roots(conn)
    assert phase_of(install, import_id) == "undone"
    assert report.kept == [] and not report.errors and not report.files.errors


def test_a_second_undo_is_refused(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    hooks, import_id = RecordingHooks(), new_import_id()
    run(crate, install, hooks=hooks, import_id=import_id)
    undo_it(install, import_id, hooks)
    after = snapshot(install)
    with pytest.raises(UndoRefused) as refused:
        undo_import.run_undo(install.env, import_id, hooks.log)
    assert [b["code"] for b in refused.value.blockers] == [undo_import.U_ALREADY]
    assert snapshot(install) == after


def test_a_file_edited_after_the_import_survives_and_is_listed(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    before = snapshot(install)
    hooks, import_id = RecordingHooks(), new_import_id()
    run(crate, install, hooks=hooks, import_id=import_id)
    placed = sorted((install.claude / "projects").rglob("*.jsonl"))
    edited = placed[0]
    edited.write_bytes(edited.read_bytes() + b'{"type":"user","note":"written after the import"}\n')

    report = undo_it(install, import_id, hooks)

    assert edited.is_file() and b"written after the import" in edited.read_bytes(), "someone's bytes are never deleted"
    assert str(edited) in report.files.kept and any(str(edited) == k["what"] for k in report.as_json()["kept"])
    assert all(not p.exists() for p in placed[1:]), "the untouched transcripts went"
    assert snapshot(install) != before
    edited.unlink()
    assert database_rows(db_path_for(install.state)) == before["dbs"]["carnivore.db"]


def test_a_row_changed_after_the_import_stays_with_its_project_and_is_listed(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    hooks, import_id = RecordingHooks(), new_import_id()
    run(crate, install, hooks=hooks, import_id=import_id)
    with closing(connect(db_path_for(install.state))) as conn:
        conn.execute("UPDATE sessions SET title = 'renamed by the owner' WHERE id = (SELECT MIN(id) FROM sessions)")
        conn.commit()

    plan = undo_import.plan_undo(install.env, import_id, hooks.log)
    assert plan.ok
    kept = {(k["what"].split(" row ")[0], k["why"]) for k in plan.as_json()["kept"]}
    assert ("sessions", "changed since the import") in kept
    undo_import.run_undo(install.env, import_id, hooks.log)

    with closing(connect(db_path_for(install.state), create=False)) as conn:
        titles = [r[0] for r in conn.execute("SELECT title FROM sessions")]
        assert titles == ["renamed by the owner"], "only the changed session stays; the other one went"
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1, "its project stays too: a kept row still points at it"


def test_a_later_import_from_the_same_source_blocks_the_undo(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    hooks, import_id = RecordingHooks(), new_import_id()
    run(crate, install, hooks=hooks, import_id=import_id)
    with closing(connect(db_path_for(install.state))) as conn:
        entry = ledger.read_entry(conn, import_id)
        ledger.write_entry(conn, "imp-29991231T000000Z-ffffffff", {**entry, "key_map": {}})
        conn.commit()
    before = snapshot(install)
    plan = undo_import.plan_undo(install.env, import_id, hooks.log)
    assert [b["code"] for b in plan.blockers] == [undo_import.U_LATER_IMPORT]
    with pytest.raises(UndoRefused):
        undo_import.run_undo(install.env, import_id, hooks.log)
    assert snapshot(install) == before, "a refused undo writes nothing"


def test_an_import_without_a_record_cannot_be_undone(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    hooks, import_id = RecordingHooks(), new_import_id()
    run(crate, install, hooks=hooks, import_id=import_id)
    with closing(connect(db_path_for(install.state))) as conn:
        conn.execute("DELETE FROM meta WHERE key = ?", (ledger.UNDO_PREFIX + import_id,))
        conn.commit()
    assert [b["code"] for b in undo_import.plan_undo(install.env, import_id, hooks.log).blockers] == [undo_import.U_NO_RECORD]
    assert [b["code"] for b in undo_import.plan_undo(install.env, "imp-20260101T000000Z-00000000", []).blockers] == [undo_import.U_NOT_FOUND]


def test_an_undone_import_no_longer_feeds_the_next_one(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    hooks, first = RecordingHooks(), new_import_id()
    run(crate, install, hooks=hooks, import_id=first)
    undo_it(install, first, hooks)
    again = run(crate, install, import_id=new_import_id())
    assert again.rows["cloude.db.sessions"]["inserted"] == 2 and again.state in ("done", "done_with_warnings")


def test_boards_relink_and_backup_points_are_undone_to_the_snapshot(tmp_path: Path) -> None:
    crate = boards_rig.export_rig(tmp_path)
    install, root, vault = boards_rig.wired(tmp_path, crate)
    local = boards_rig.board_raw(boards_rig.SLUG_MINE, None)
    local["board"]["title"] = "a local board with the crate's slug"
    boards_rig.make_board(root, local)
    own = vault.capture_folder(boards_rig.UNIT, root)
    assert own.status in ("written", "no_files")
    target_vault = tmp_path / "target-vault"
    before = snapshot(install, root, target_vault)
    hooks, import_id = RecordingHooks(), new_import_id()
    receipt = run(crate, install, hooks=hooks, import_id=import_id)
    assert receipt.backups["folders"]["adopted"] == 2 and snapshot(install, root, target_vault) != before

    undo_it(install, import_id, hooks, vault=vault)

    same(snapshot(install, root, target_vault), before)
    assert True, "boards, the relinked sidecar's bytes, the vault points and every row are as before"


def test_project_files_are_undone_to_the_snapshot(tmp_path: Path) -> None:
    crate = files_rig.project_crate(tmp_path)
    install = files_rig.target(tmp_path, crate)
    before = snapshot(install)
    hooks, import_id = RecordingHooks(), new_import_id()
    request = ImportRequest(include_project_files=True, mode="relocate", new_root=str(install.projects / "moved"))
    from src.core.crate_import import apply as ap
    from src.core.crate_import.plan import build_plan
    from src.cplugs.sdk import crate_format as cf

    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
        assert plan["ok"], plan["blockers"]
        ap.apply_import(reader, install.env, request, crate_sha256=crate.sha256, fingerprint=plan["fingerprint"], import_id=import_id, hooks=hooks)
    assert snapshot(install) != before

    undo_it(install, import_id, hooks)

    assert snapshot(install) == before


def test_the_preview_counts_match_the_result_counts_with_nested_folders(tmp_path: Path) -> None:
    from src.core.crate_import import apply as ap
    from src.core.crate_import.plan import build_plan
    from src.core.crate_import.undo import log_counts
    from src.cplugs.sdk import crate_format as cf

    crate = files_rig.project_crate(tmp_path)
    install = files_rig.target(tmp_path, crate)
    hooks, import_id = RecordingHooks(), new_import_id()
    request = ImportRequest(include_project_files=True, mode="relocate", new_root=str(install.projects / "moved"))
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
        ap.apply_import(reader, install.env, request, crate_sha256=crate.sha256, fingerprint=plan["fingerprint"], import_id=import_id, hooks=hooks)
    preview = log_counts(hooks.log)
    assert preview["folders"] >= 2, preview

    result = undo_it(install, import_id, hooks).as_json()

    assert (result["files_removed"], result["folders_removed"]) == (preview["files"], preview["folders"])


def test_a_file_logged_twice_is_counted_once_in_the_preview(tmp_path: Path) -> None:
    from src.core.crate_import import apply as ap
    from src.core.crate_import.plan import build_plan
    from src.core.crate_import.undo import OP_FILE, log_counts
    from src.cplugs.sdk import crate_format as cf

    crate = files_rig.project_crate(tmp_path)
    install = files_rig.target(tmp_path, crate)
    hooks, import_id = RecordingHooks(), new_import_id()
    request = ImportRequest(include_project_files=True, mode="relocate", new_root=str(install.projects / "moved"))
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)
        ap.apply_import(reader, install.env, request, crate_sha256=crate.sha256, fingerprint=plan["fingerprint"], import_id=import_id, hooks=hooks)
    first_file = next(e for e in hooks.log if e.get("op") == OP_FILE)
    hooks.log.append(dict(first_file))
    preview = log_counts(hooks.log)

    result = undo_it(install, import_id, hooks).as_json()

    assert (result["files_removed"], result["folders_removed"]) == (preview["files"], preview["folders"])
