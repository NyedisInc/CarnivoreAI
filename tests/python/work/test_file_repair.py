
from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts.work import repair_task_file_aliases as cli
from src.core.work import file_refs, file_repair
from src.core.work.file_repair import repair
from tests.python.pack.test_task_manager_side_compat import ITEM_INSERT, machine, sql

ID = "abcd1234"
NAME = f"{ID}-x.png"


def entry(path: str) -> Dict[str, Any]:
    return {"id": ID, "name": "x.png", "mime": "image/png", "size": 5, "path": path}


def world(tmp_path: Path) -> Dict[str, Any]:
    state = machine(tmp_path, "s")
    own = Path(state) / "cplugs" / "huddle" / "files" / "1"
    own.mkdir(parents=True)
    (own / NAME).write_bytes(b"bytes")
    root = tmp_path / "tm"
    task = root / "p-1" / "t-1"
    (task / "pastes").mkdir(parents=True)
    (task / ".tm-task").write_text(json.dumps({"item_id": 1}))
    (task / "pastes" / NAME).write_bytes(b"bytes")
    own = root / "p-1" / "t-5"
    (own / "pastes").mkdir(parents=True)
    (own / ".tm-task").write_text(json.dumps({"item_id": 5}))
    (own / "pastes" / NAME).write_bytes(b"bytes")
    paths = {1: f"files/1/{NAME}", 2: f"files/1/{NAME}", 3: str(task / "pastes" / NAME), 4: f"files/9/{NAME}", 5: str(own / "pastes" / NAME)}
    for item, path in paths.items():
        sql(state, ITEM_INSERT, ("16", f"item {item}", "", item, "open"))
        sql(state, "INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, parts) VALUES (?, 'joe', 'say', 'm', 1, ?, ?)",
            (item, item, json.dumps({"files": [entry(path)]})))
    return {"state": state, "root": root, "task_file": task / "pastes" / NAME, "own_absolute": str(own / "pastes" / NAME)}


def paths_of(state: str) -> List[str]:
    return [json.loads(r["parts"])["files"][0]["path"] for r in sql(state, "SELECT parts FROM work_messages ORDER BY id")]


def test_a_dry_run_lists_the_copies_and_writes_nothing(tmp_path: Path) -> None:
    w = world(tmp_path)
    before = paths_of(w["state"])
    report = repair(Path(w["state"]), [w["root"]])
    files = Path(w["state"]) / "cplugs" / "huddle" / "files"
    assert not report.applied and report.messages == 2 and len(report.copies) == 2
    assert {dest for _src, dest in report.copies} == {str(files / "2" / NAME), str(files / "3" / NAME)}
    assert paths_of(w["state"]) == before and not (files / "2").exists() and not (files / "3").exists()


def test_apply_gives_each_item_its_own_copy_and_leaves_the_sources(tmp_path: Path) -> None:
    w = world(tmp_path)
    report = repair(Path(w["state"]), [w["root"]], apply=True)
    files = Path(w["state"]) / "cplugs" / "huddle" / "files"
    assert report.applied and report.messages == 2
    assert paths_of(w["state"]) == [f"files/1/{NAME}", f"files/2/{NAME}", f"files/3/{NAME}", f"files/9/{NAME}", w["own_absolute"]], "item 5's own file is not touched"
    assert (files / "2" / NAME).read_bytes() == b"bytes" == (files / "3" / NAME).read_bytes()
    assert (files / "1" / NAME).exists() and w["task_file"].exists(), "the sources are never touched"


def test_a_second_run_finds_nothing_and_an_own_file_is_left_alone(tmp_path: Path) -> None:
    w = world(tmp_path)
    repair(Path(w["state"]), [w["root"]], apply=True)
    again = repair(Path(w["state"]), [w["root"]], apply=True)
    assert again.messages == 0 and again.copies == [] and repair(Path(w["state"]), [w["root"]]).messages == 0


def test_a_reference_with_no_bytes_is_left_as_it_is_and_reported(tmp_path: Path) -> None:
    w = world(tmp_path)
    report = repair(Path(w["state"]), [w["root"]], apply=True)
    assert report.unresolved == ["x.png"] and paths_of(w["state"])[3] == f"files/9/{NAME}"


def test_the_cli_is_a_dry_run_unless_apply_is_given(tmp_path: Path) -> None:
    w = world(tmp_path)
    out = io.StringIO()
    assert cli.main(["--state", w["state"], "--root", str(w["root"])], out) == 0
    assert "would copy" in out.getvalue() and "dry run: 2 message(s)" in out.getvalue() and paths_of(w["state"])[1] == f"files/1/{NAME}"
    out = io.StringIO()
    assert cli.main(["--state", w["state"], "--root", str(w["root"]), "--apply"], out) == 0
    assert "copied:" in out.getvalue() and paths_of(w["state"])[1] == f"files/2/{NAME}"
    assert cli.main(["--state", str(tmp_path / "nope")], io.StringIO()) == 2


def test_a_writer_cannot_slip_in_between_the_repair_s_read_and_its_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(tmp_path)
    db = Path(w["state"]) / "carnivore.db"
    real = file_refs.FileHome.rewrite_message
    outcome: List[str] = []

    def racing(self: file_refs.FileHome, parts: Any, text: Any, old: int, new: int, select: Any = None) -> Any:
        result = real(self, parts, text, old, new, select)
        if not outcome:
            other = sqlite3.connect(str(db), timeout=0.2)
            try:
                other.execute("UPDATE work_messages SET parts = '', text = text || ' [x.png was removed]' WHERE item_id = 2")
                other.commit()
                outcome.append("written")
            except sqlite3.OperationalError:
                outcome.append("locked")
            finally:
                other.close()
        return result

    monkeypatch.setattr(file_refs.FileHome, "rewrite_message", racing)
    repair(Path(w["state"]), [w["root"]], apply=True)
    assert outcome == ["locked"], "the concurrent write got in between the read and the write"
    assert paths_of(w["state"])[1] == f"files/2/{NAME}"


def test_a_message_that_changed_after_it_was_read_is_skipped_and_counted(tmp_path: Path) -> None:
    w = world(tmp_path)
    conn = sqlite3.connect(str(Path(w["state"]) / "carnivore.db"), isolation_level=None)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id, item_id, parts FROM work_messages WHERE item_id = 2").fetchone()
    stale = (int(row["id"]), 2, '{"files": []}', '{"files": [{"path": "files/2/new"}]}')
    fresh = (int(row["id"]), 2, row["parts"], '{"files": [{"path": "files/2/new"}]}')
    assert file_repair._write(conn, [stale]) == 1 and conn.execute("SELECT parts FROM work_messages WHERE id = ?", (row["id"],)).fetchone()[0] == row["parts"]
    assert file_repair._write(conn, [fresh]) == 0
    conn.close()


def test_a_failure_part_way_removes_the_copies_and_changes_no_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(tmp_path)
    before = paths_of(w["state"])
    monkeypatch.setattr(file_repair, "_next_seq", lambda conn: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        repair(Path(w["state"]), [w["root"]], apply=True)
    files = Path(w["state"]) / "cplugs" / "huddle" / "files"
    assert paths_of(w["state"]) == before and not (files / "2").exists() and not (files / "3").exists()
    assert (files / "1" / NAME).exists(), "the sources are never touched"
