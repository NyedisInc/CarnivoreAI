
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import Dict, List, Optional, Set

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import db_path_for
from src.core.lineage import live, scan
from tests.s7_helpers import migrated_connection

HEAD = {"type": "user", "entrypoint": "cli", "timestamp": "2026-10-09T11:00:00Z"}
FILLER = {"type": "assistant", "message": {"content": "x" * 900}}
FILLER_LINES = 3500


def _compact(tag: str) -> Dict[str, object]:
    return {"type": "system", "subtype": "compact_boundary", "uuid": f"rec-{tag}", "timestamp": f"2026-10-10T0{tag}:00:00Z",
            "compactMetadata": {"trigger": "auto", "preTokens": 1000 * int(tag)}}


def _lines(records: List[Dict[str, object]]) -> str:
    return "".join(json.dumps(r) + "\n" for r in records)


@pytest.fixture()
def world(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    folder = tmp_path / "projects" / "-proj"
    folder.mkdir(parents=True)

    class World:

        def __init__(self) -> None:
            self.state, self.folder, self.db = state, folder, db_path_for(state)
            self.path = folder / "conv-a.jsonl"

        def sweep(self) -> live.SweepReport:
            return live.sweep(self.db, self.state, roots=[tmp_path / "projects"], include_codex=False)

        def milestones(self) -> List[tuple]:
            with closing(sqlite3.connect(self.db)) as raw:
                return raw.execute("SELECT jsonl_line, jsonl_offset, json_extract(detail_json, '$.record_uuid') "
                                   "FROM conversation_milestones ORDER BY jsonl_line").fetchall()

    return World()


@pytest.fixture()
def bytes_read(monkeypatch):
    total = [0]
    real_open = pathlib.Path.open

    class Counting:

        def __init__(self, handle) -> None:
            self._handle = handle

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *exc):
            return self._handle.__exit__(*exc)

        def read(self, *args):
            data = self._handle.read(*args)
            total[0] += len(data)
            return data

        def __getattr__(self, name):
            return getattr(self._handle, name)

    def counting_open(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        return Counting(handle) if "b" in mode and self.suffix == ".jsonl" else handle

    monkeypatch.setattr(pathlib.Path, "open", counting_open)
    return total


def _big(world) -> None:
    world.path.write_text(_lines([HEAD] + [FILLER] * FILLER_LINES + [_compact("1")]))


def test_an_appended_transcript_is_read_from_the_old_end_not_from_the_top(world, bytes_read):
    _big(world)
    world.sweep()
    size = world.path.stat().st_size
    with world.path.open("ab") as handle:
        handle.write(json.dumps(FILLER).encode() + b"\n")
    bytes_read[0] = 0
    report = world.sweep()
    assert report.examined == 1
    assert bytes_read[0] < size // 3, f"read {bytes_read[0]} bytes of a {size} byte file that grew by one line"


def _assert_stored_where_a_whole_scan_finds(world, only: Optional[Set[str]] = None) -> None:
    stored = {m[2]: (m[0], m[1]) for m in world.milestones()}
    whole = {h.detail["record_uuid"]: (h.line, h.offset) for h in scan.compacts_of(world.path)
             if only is None or h.detail["record_uuid"] in only}
    assert whole, "the test file must hold a boundary"
    assert {u: stored.get(u) for u in whole} == whole


def test_a_compact_appended_later_gets_the_line_and_offset_a_full_scan_gives_it(world):
    _big(world)
    world.sweep()
    with world.path.open("a") as handle:
        handle.write(_lines([FILLER, _compact("2"), FILLER]))
    assert world.sweep().counts["compacts"] == 1
    assert [m[2] for m in world.milestones()] == ["rec-1", "rec-2"]
    _assert_stored_where_a_whole_scan_finds(world)


def test_a_shorter_file_is_read_whole(world):
    _big(world)
    world.sweep()
    world.path.write_text(_lines([HEAD, _compact("3")]))
    assert world.sweep().counts["compacts"] == 1
    assert {m[2] for m in world.milestones()} == {"rec-1", "rec-3"}
    _assert_stored_where_a_whole_scan_finds(world)


def test_a_rewritten_file_that_grew_is_read_whole(world):
    world.path.write_text(_lines([HEAD, _compact("1")]))
    world.sweep()
    world.path.write_text(_lines([HEAD, FILLER, _compact("4"), FILLER, FILLER]))
    assert world.sweep().counts["compacts"] == 1
    assert {m[2] for m in world.milestones()} == {"rec-1", "rec-4"}
    _assert_stored_where_a_whole_scan_finds(world)


def test_a_replacement_of_exactly_the_same_size_is_read_whole(world):
    world.path.write_text(_lines([HEAD, FILLER, FILLER, _compact("1")]))
    world.sweep()
    world.path.write_text(_lines([HEAD, FILLER, _compact("2"), FILLER]))
    assert world.sweep().counts["compacts"] == 1
    _assert_stored_where_a_whole_scan_finds(world)


def test_a_longer_file_whose_only_change_is_its_first_line_is_read_whole(world):
    _big(world)
    world.sweep()
    head, rest = world.path.read_text().split("\n", 1)
    world.path.write_text(json.dumps({**HEAD, "note": "y" * 60}) + "\n" + rest + _lines([_compact("2")]))
    assert world.sweep().counts["compacts"] == 1
    _assert_stored_where_a_whole_scan_finds(world, only={"rec-2"})


def test_a_half_written_last_line_is_picked_up_once_it_is_whole(world):
    world.path.write_text(_lines([HEAD, FILLER]))
    world.sweep()
    whole = json.dumps(_compact("5"))
    with world.path.open("a") as handle:
        handle.write(whole[:30])
    assert world.sweep().counts["compacts"] == 0
    with world.path.open("a") as handle:
        handle.write(whole[30:] + "\n")
    assert world.sweep().counts["compacts"] == 1
    assert [(m[0], m[2]) for m in world.milestones()] == [(3, "rec-5")]


def test_a_finished_last_line_without_its_newline_is_found_and_not_duplicated(world):
    world.path.write_text(_lines([HEAD, FILLER]) + json.dumps(_compact("6")))
    assert world.sweep().counts["compacts"] == 1
    with world.path.open("a") as handle:
        handle.write("\n" + json.dumps(FILLER) + "\n")
    assert world.sweep().counts["compacts"] == 0
    assert [(m[0], m[2]) for m in world.milestones()] == [(3, "rec-6")]


def test_a_cursor_from_before_the_resume_point_existed_still_works(world, bytes_read):
    _big(world)
    world.sweep()
    cursor = live.load_cursor(world.state)
    key = str(world.path)
    cursor[key] = cursor[key][:2]
    live.save_cursor(world.state, cursor)
    assert world.sweep().unchanged == 1
    with world.path.open("a") as handle:
        handle.write(_lines([_compact("7")]))
    assert world.sweep().counts["compacts"] == 1
    size = world.path.stat().st_size
    with world.path.open("a") as handle:
        handle.write(_lines([FILLER]))
    bytes_read[0] = 0
    assert world.sweep().examined == 1
    assert bytes_read[0] < size // 3


def test_milestones_a_database_lost_come_back_when_the_transcript_next_changes(world):
    _big(world)
    world.sweep()
    with closing(sqlite3.connect(world.db)) as raw:
        raw.execute("DELETE FROM conversation_milestones")
        raw.commit()
    assert world.milestones() == []
    with world.path.open("a") as handle:
        handle.write(_lines([FILLER, _compact("2")]))
    assert world.sweep().counts["compacts"] == 2
    assert [m[2] for m in world.milestones()] == ["rec-1", "rec-2"]
    _assert_stored_where_a_whole_scan_finds(world)


def test_a_database_that_kept_its_milestones_still_gets_the_cheap_tail_read(world, bytes_read):
    _big(world)
    world.sweep()
    size = world.path.stat().st_size
    with world.path.open("a") as handle:
        handle.write(_lines([FILLER]))
    bytes_read[0] = 0
    world.sweep()
    assert bytes_read[0] < size // 3


def test_boundaries_sharing_a_timestamp_do_not_make_every_change_a_whole_read(world, bytes_read):
    twin = {**_compact("1"), "uuid": "rec-1b"}
    world.path.write_text(_lines([HEAD] + [FILLER] * FILLER_LINES + [_compact("1"), twin]))
    world.sweep()
    assert len(world.milestones()) == 1
    size = world.path.stat().st_size
    with world.path.open("a") as handle:
        handle.write(_lines([FILLER]))
    bytes_read[0] = 0
    assert world.sweep().examined == 1
    assert bytes_read[0] < size // 3, f"read {bytes_read[0]} bytes of a {size} byte file that grew by one line"


def test_a_resume_point_with_a_wrong_line_count_is_refused(world):
    _big(world)
    first = scan.scan_compacts(world.path)
    with world.path.open("a") as handle:
        handle.write(_lines([_compact("2")]))
    bad = replace(first.resume, lines=first.resume.lines + 5)
    assert scan.scan_compacts(world.path, bad).hits == scan.compacts_of(world.path)


def test_a_quiet_pass_reads_no_transcript_bytes(world, bytes_read):
    _big(world)
    world.sweep()
    bytes_read[0] = 0
    assert world.sweep().unchanged == 1
    assert bytes_read[0] == 0


def test_one_conversation_id_in_two_roots_is_idle_whichever_copy_is_listed_first(world, bytes_read, tmp_path):
    _big(world)
    second = tmp_path / "projects-b"
    (second / "-proj").mkdir(parents=True)
    (second / "-proj" / world.path.name).write_text(_lines([HEAD] + [FILLER] * (FILLER_LINES // 2) + [_compact("2")]))
    first = tmp_path / "projects"

    def sweep(*roots) -> live.SweepReport:
        return live.sweep(world.db, world.state, roots=list(roots), include_codex=False)

    sweep(first, second)
    sweep(second, first)
    bytes_read[0] = 0
    reports = [sweep(first, second), sweep(second, first), sweep(first, second)]
    assert [r.examined for r in reports] == [0, 0, 0]
    assert bytes_read[0] == 0


def test_a_cursor_keyed_by_conversation_id_is_adopted_not_reread(world, bytes_read, monkeypatch):
    _big(world)
    world.sweep()
    path_key = str(world.path)
    cursor = live.load_cursor(world.state)
    live.save_cursor(world.state, {"conv-a": cursor.pop(path_key)})
    bytes_read[0] = 0
    report = world.sweep()
    assert (report.examined, report.unchanged, bytes_read[0]) == (0, 1, 0)
    assert path_key in live.load_cursor(world.state)
    monkeypatch.setattr(scan, "roots", lambda: (world.folder.parent,))
    live.sweep(world.db, world.state, include_codex=False)
    assert set(live.load_cursor(world.state)) == {path_key}


def test_a_looping_symlink_transcript_does_not_stop_the_pass(world):
    _big(world)
    (world.folder / "loop.jsonl").symlink_to(world.folder / "loop.jsonl")
    assert world.sweep().examined == 1


def test_a_one_root_pass_keeps_the_old_id_keys_of_files_it_did_not_list(world):
    _big(world)
    world.sweep()
    cursor = live.load_cursor(world.state)
    cursor["other-conv"] = [1, 2]
    live.save_cursor(world.state, cursor)
    world.sweep()
    assert "other-conv" in live.load_cursor(world.state)


def test_the_cursor_key_of_a_symlinked_transcript_is_its_own_path_not_its_target(world):
    _big(world)
    link = world.folder / "link.jsonl"
    link.symlink_to(world.path)
    assert live.cursor_key(link) == str(link)
