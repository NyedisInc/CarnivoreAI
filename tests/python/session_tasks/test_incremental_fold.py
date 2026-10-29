
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from src.core.session_tasks import reader as reader_mod
from src.core.session_tasks.reader import TaskReader, fold_transcript


def _use(block_id: str, name: str, args: Dict[str, Any]) -> str:
    rec = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": block_id, "name": name, "input": args}]}}
    return json.dumps(rec) + "\n"


def _made(block_id: str, task_id: str) -> str:
    rec = {"type": "user", "toolUseResult": {"task": {"id": task_id}},
           "message": {"content": [{"type": "tool_result", "tool_use_id": block_id, "content": "Task #%s created" % task_id}]}}
    return json.dumps(rec) + "\n"


def _shape(items: List[Any]) -> List[Any]:
    return [(i.id, i.subject, i.active_form, i.status) for i in items]


def _same(reader: TaskReader, path: Path) -> None:
    assert _shape(reader.read(path)) == _shape(fold_transcript(path))


def test_append_truncate_rotate_equal_full_fold(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text(_use("a", "TaskCreate", {"subject": "one"}) + _made("a", "1"))
    reader = TaskReader()
    _same(reader, path)
    with path.open("a") as fh:
        fh.write(_use("u", "TaskUpdate", {"taskId": "1", "status": "completed"}))
        fh.write(_use("b", "TaskCreate", {"subject": "two"}) + _made("b", "2"))
    _same(reader, path)
    assert [i.status for i in reader.read(path)] == ["completed", "pending"]
    path.write_text(_use("t", "TodoWrite", {"todos": [{"content": "x", "status": "pending"}]}))
    _same(reader, path)
    inode = path.stat().st_ino
    other = tmp_path / "new.jsonl"
    other.write_text(_use("t", "TodoWrite", {"todos": [{"content": "y", "status": "in_progress"}]}) * 3)
    os.replace(other, path)
    assert path.stat().st_ino != inode
    _same(reader, path)


def test_partial_trailing_line_matches_full_fold_and_is_not_double_applied(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    first = _use("a", "TaskCreate", {"subject": "one"}) + _made("a", "1")
    update = _use("u", "TaskUpdate", {"taskId": "1", "subject": "renamed"})
    path.write_text(first + update.rstrip("\n"))
    reader = TaskReader()
    _same(reader, path)
    with path.open("a") as fh:
        fh.write("\n")
    _same(reader, path)
    cut = update[:20]
    path.write_text(first + cut)
    _same(reader, path)
    path.write_text(first + update)
    _same(reader, path)
    assert reader.read(path)[0].subject == "renamed"


def test_append_reads_only_new_bytes(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "c.jsonl"
    path.write_text(_use("a", "TaskCreate", {"subject": "one"}) + _made("a", "1") + "noise\n" * 2000)
    reader = TaskReader()
    reader.read(path)
    with path.open("a") as fh:
        fh.write(_use("u", "TaskUpdate", {"taskId": "1", "status": "completed"}))
    seen: List[bytes] = []
    real = reader_mod._feed_line
    monkeypatch.setattr(reader_mod, "_feed_line", lambda fold, line: (seen.append(line), real(fold, line))[1])
    assert reader.read(path)[0].status == "completed"
    assert len(seen) == 1


def test_cache_is_bounded(tmp_path: Path) -> None:
    reader = TaskReader(max_entries=2)
    for n in range(5):
        p = tmp_path / ("%d.jsonl" % n)
        p.write_text(_use("a", "TodoWrite", {"todos": [{"content": "t", "status": "pending"}]}))
        reader.read(p)
    assert len(reader._entries) == 2
    gone = tmp_path / "4.jsonl"
    gone.unlink()
    try:
        reader.read(gone)
    except reader_mod.TranscriptUnreadable:
        pass
    assert gone not in reader._entries
