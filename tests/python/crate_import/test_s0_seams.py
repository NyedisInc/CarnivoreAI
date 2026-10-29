
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.blobcodec.place import PlaceConflict, PlaceMismatch, file_matches, place_no_clobber, write_verified
from src.core.db import connect, db_path_for, get_meta
from src.core.db_migration import ensure_db_migrated
from src.core.exports.store import crate_written_key
from src.core.pack.migrate import task_manager_side
from src.core.project_move.paths import PathMapping, rebase_journal_for
from src.core.project_tombstones import record_tombstone, tombstoned_roots
from src.core.project_writes import insert_project_row, remove_created_project
from src.core.work.import_rows import import_rows
from src.cplugs.crate import service_crates
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request

FIXTURES_V11 = Path(__file__).resolve().parents[2] / "fixtures" / "crate" / "v1.1"
V11_SUMS_SHA256 = "6bfae4519ac6f689d3f9788da708400740c9fecab0f86e4e1a0723b0a20fac14"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()



def test_the_placer_never_replaces_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "t.jsonl"
    dest.write_bytes(b"mine\n")
    with pytest.raises(PlaceConflict):
        write_verified([b"theirs\n"], dest, length=7, sha256=_sha(b"theirs\n"))
    assert dest.read_bytes() == b"mine\n"

    def no_links(src: Any, dst: Any, **kw: Any) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    with pytest.raises(PlaceConflict):
        write_verified([b"theirs\n"], dest, length=7, sha256=_sha(b"theirs\n"))
    assert dest.read_bytes() == b"mine\n"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".partial")]
    fresh = tmp_path / "new.jsonl"
    assert write_verified([b"ab", b"cd"], fresh, length=4, sha256=_sha(b"abcd"), mode=0o640) == 4
    assert fresh.read_bytes() == b"abcd" and file_matches(fresh, _sha(b"abcd"), 4) and not file_matches(fresh, _sha(b"abcd"), 5)


def test_the_placer_refuses_wrong_bytes_and_leaves_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "x.bin"
    with pytest.raises(PlaceMismatch):
        write_verified([b"abc"], dest, length=3, sha256=_sha(b"abd"))
    assert list(tmp_path.iterdir()) == []



def _work_state(tmp_path: Path) -> str:
    folder = tmp_path / "work"
    folder.mkdir()
    task_manager_side._storage(str(folder)).connect(True).close()
    return str(folder)


def _live_texts(state: str, list_key: str) -> List[str]:
    with closing(task_manager_side._storage(state).connect(True)) as conn:
        return [r[0] for r in conn.execute("SELECT text FROM work_items WHERE list_key = ? AND deleted = 0 ORDER BY id", (list_key,))]


def _item(item_id: int, text: str) -> Dict[str, Any]:
    return {"id": item_id, "list_key": "9", "text": text, "note": "", "position": item_id, "created_by": "claude", "state": "open",
            "created_at": 1.0, "updated_at": 1.0, "deleted": 0, "lane": "work", "card_origin": "", "swarm_ref": "", "created_key": ""}


def test_import_rows_adds_beside_live_items_and_pack_still_replaces(tmp_path: Path) -> None:
    state = _work_state(tmp_path)
    task_manager_side.import_list(state, "4", {"items": [_item(1, "live here")], "messages": [], "groups": []}, {})
    crate = {"items": [_item(1, "from crate"), _item(2, "second")], "messages": [], "groups": []}
    with closing(task_manager_side._storage(state).connect(True)) as conn, conn:
        undo = import_rows(conn, "4", crate, {}, replace_existing=False)
    assert _live_texts(state, "4") == ["live here", "from crate", "second"]
    assert undo["replaced_item_ids"] == [] and len(undo["item_ids"]) == 2
    task_manager_side.import_list(state, "4", crate, {})
    assert _live_texts(state, "4") == ["from crate", "second"]



@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    c = connect(db_path_for(state))
    yield c
    c.close()


def _session(c: sqlite3.Connection, name: str, working_dir: str) -> int:
    cur = c.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, lifecycle, working_dir, "
        "project_attribution, created_at, updated_at) VALUES (?, 'cloude', ?, 1, 'created', 'running', ?, 'unknown', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (f"u-{name}", name, working_dir))
    return int(cur.lastrowid)


def test_insert_project_row_in_a_caller_transaction_and_its_undo(conn: sqlite3.Connection, tmp_path: Path) -> None:
    root = str(tmp_path / "app")
    record_tombstone(conn, root, "app")
    idle, live = _session(conn, "idle", root + "/a"), _session(conn, "live", root + "/b")
    conn.execute("BEGIN IMMEDIATE")
    row, cleared, adopted = insert_project_row(conn, root=root, raw_path=root, name="app", uid="ab" * 16, source="user",
                                               skip_session_ids=frozenset({live}))
    conn.execute("COMMIT")
    assert row["uid"] == "ab" * 16 and row["root"] == root
    assert cleared == {"root": root, "display_name": "app", "deleted_at": cleared["deleted_at"]}
    assert root not in tombstoned_roots(conn)
    assert [a["id"] for a in adopted] == [idle]
    assert conn.execute("SELECT project_id FROM sessions WHERE id = ?", (live,)).fetchone()[0] is None
    assert conn.execute("SELECT project_id FROM sessions WHERE id = ?", (idle,)).fetchone()[0] == row["id"]

    conn.execute("BEGIN IMMEDIATE")
    remove_created_project(conn, row["id"], restore_tombstone=cleared, adopted_ids=adopted)
    conn.execute("COMMIT")
    assert conn.execute("SELECT 1 FROM projects WHERE id = ?", (row["id"],)).fetchone() is None
    assert conn.execute("SELECT project_id FROM sessions WHERE id = ?", (idle,)).fetchone()[0] is None
    assert tombstoned_roots(conn) == {root}

    other = str(tmp_path / "other")
    conn.execute("BEGIN IMMEDIATE")
    made, none_cleared, none_adopted = insert_project_row(conn, root=other, raw_path=other, name="other", uid=None, source="user")
    remove_created_project(conn, made["id"], restore_tombstone=none_cleared, adopted_ids=none_adopted)
    conn.execute("COMMIT")
    assert none_cleared is None and other not in tombstoned_roots(conn)



def test_rebase_journal_for_moves_only_the_imported_sessions() -> None:
    journal = {"sessions": {"a@1": {"session_uuid": "mine", "working_dir": "/old/x", "cwd": "/old/x/sub", "tmux_name": "a"},
                            "b@1": {"session_uuid": "other", "working_dir": "/old/y", "cwd": "/old/y"}},
               "offer": {"candidates": [{"session_uuid": "mine", "folder": "/old/x"}, {"session_uuid": "other", "folder": "/old/y"}]}}
    mapping = PathMapping.of([("/old", "/new"), ("/old/x", "/elsewhere")])
    assert rebase_journal_for(journal, mapping, ["mine"]) == 3
    assert journal["sessions"]["a@1"] == {"session_uuid": "mine", "working_dir": "/elsewhere", "cwd": "/elsewhere/sub", "tmux_name": "a"}
    assert journal["sessions"]["b@1"]["working_dir"] == "/old/y" and journal["offer"]["candidates"][1]["folder"] == "/old/y"
    assert journal["offer"]["candidates"][0]["folder"] == "/elsewhere"
    assert PathMapping.of([("/a", "/b")]).apply("/z") is None and PathMapping.of([("/a", "/b")]).apply("/ab") is None



def test_the_mark_is_set_by_an_export_and_not_by_a_folder_verify(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    env = env_for(w)
    plan = build_plan(env, project_request(w))
    assert plan.ok, plan.blockers
    result = run_export(env, plan, JobHandle("s0"))
    key = crate_written_key(result.bundle_id)

    def meta() -> Any:
        with closing(connect(db_path_for(Path(w.state)), create=False)) as c:
            return get_meta(c, key)

    assert meta() == result.sha256
    with closing(connect(db_path_for(Path(w.state)), create=False)) as c:
        c.execute("DELETE FROM export_pointers")
        c.execute("DELETE FROM export_bundles")
        c.execute("DELETE FROM meta WHERE key = ?", (key,))
    assert meta() is None
    report = cf.verify(result.path, "full", expected_sha256=result.sha256)
    assert report.ok
    assert service_crates._record_folder_pass(env, result.path, report, None) == result.bundle_id
    assert meta() is None



def test_the_v11_golden_folder_is_frozen_and_still_verifies() -> None:
    sums = FIXTURES_V11 / "SHA256SUMS"
    assert _sha(sums.read_bytes()) == V11_SUMS_SHA256
    for line in sums.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert _sha((FIXTURES_V11 / rel).read_bytes()) == digest, rel
    for name, version in (("project-own.crate", (1, 1)), ("session-own.crate", (1, 0))):
        path = FIXTURES_V11 / name
        report = cf.verify(path, "full", expected_sha256=_sha(path.read_bytes()))
        assert report.ok, (name, report.codes)
        with cf.open_crate(path) as reader:
            assert reader.format_version == version
    with cf.open_crate(FIXTURES_V11 / "project-own.crate") as reader:
        homes = {h.kind for h in reader.manifest.homes}
        assert {"project", "plugin-synth"} <= homes
        assert {f.role for f in reader.files()} >= {"project_file", "plugin_file"}
    assert json.loads((FIXTURES_V11 / "expected" / "coverage.json").read_text())["seen"]["homes"]
