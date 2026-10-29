
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_trail_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_trail_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.migration_trail import (
    TRAIL_READ_ABSENT,
    TRAIL_READ_OK,
    TRAIL_READ_TRUNCATED_TAIL,
    TRAIL_READ_UNREADABLE,
    MigrationTrail,
    TrailEntry,
    find_unclosed,
    read_trail,
)
from src.core.trail_entry import FIELD_ORDER


def _trail(tmp_path: Path) -> MigrationTrail:
    return MigrationTrail(tmp_path)


def test_entry_uuid_and_kind_are_the_first_two_keys() -> None:
    assert FIELD_ORDER[0] == "entry_uuid"
    assert FIELD_ORDER[1] == "kind"


def test_absent_trail_is_its_own_state(tmp_path) -> None:
    result = read_trail(tmp_path / "migration_trail.jsonl")
    assert result.status == TRAIL_READ_ABSENT
    assert result.entries == []
    assert result.is_usable is True


def test_append_is_durable_and_parses_back(tmp_path) -> None:
    trail = _trail(tmp_path)
    started = trail.open_step("schema", "1", "2", app_version="0.8.2")
    trail.close_step(started, "completed", backup_path="b", backup_verified=1)

    raw = trail.path.read_bytes()
    assert raw.endswith(b"\n")
    result = trail.read()
    assert result.status == TRAIL_READ_OK
    assert [e.status for e in result.entries] == ["started", "completed"]
    assert result.entries[0].entry_uuid == result.entries[1].entry_uuid
    assert result.entries[1].backup_verified == 1


def test_unclosed_started_is_detected_as_interrupted(tmp_path) -> None:
    trail = _trail(tmp_path)
    trail.open_step("schema", "1", "2")
    result = trail.read()
    assert result.status == TRAIL_READ_OK
    unclosed = find_unclosed(result.entries)
    assert len(unclosed) == 1
    assert unclosed[0].status == "started"


def test_closed_entries_are_not_reported_unclosed(tmp_path) -> None:
    for closing_status in (
        "completed",
        "failed",
        "interrupted",
        "completed_after_interrupt",
    ):
        trail = _trail(tmp_path / closing_status)
        started = trail.open_step("schema", "1", "2")
        trail.close_step(started, closing_status)
        assert find_unclosed(trail.read().entries) == []


def test_truncated_last_line_is_recovered_as_interrupted(tmp_path) -> None:
    trail = _trail(tmp_path)
    started = trail.open_step("schema", "1", "2")
    trail.close_step(started, "completed")
    second = TrailEntry(
        entry_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        kind="schema",
        status="started",
        started_at="2026-08-18T09:00:00.000000Z",
        from_version="2",
        to_version="3",
    )
    line = second.to_line().rstrip("\n")
    with open(trail.path, "a") as handle:
        handle.write(line[: len(line) // 2])

    result = trail.read()
    assert result.status == TRAIL_READ_TRUNCATED_TAIL
    assert result.is_usable is True
    assert result.corrupt_line_no == 3
    recovered = [e for e in result.entries if e.recovered_partial]
    assert len(recovered) == 1
    assert recovered[0].entry_uuid == second.entry_uuid
    assert recovered[0].kind == "schema"
    assert [e.entry_uuid for e in find_unclosed(result.entries)] == [
        second.entry_uuid
    ]


def test_corrupt_middle_line_makes_the_trail_unreadable(tmp_path) -> None:
    trail = _trail(tmp_path)
    for version in (1, 2, 3):
        started = trail.open_step("schema", str(version), str(version + 1))
        trail.close_step(started, "completed")

    lines = trail.path.read_text().splitlines(keepends=True)
    lines[2] = "{this is not json at all\n"
    trail.path.write_text("".join(lines))

    result = trail.read()
    assert result.status == TRAIL_READ_UNREADABLE
    assert result.is_usable is False
    assert result.corrupt_line_no == 3
    assert result.status != TRAIL_READ_ABSENT
    assert len(result.entries) == 2


def test_truncated_tail_and_corrupt_middle_differ(tmp_path) -> None:
    def build(directory: Path) -> MigrationTrail:
        t = MigrationTrail(directory)
        for version in (1, 2):
            s = t.open_step("schema", str(version), str(version + 1))
            t.close_step(s, "completed")
        return t

    tail_trail = build(tmp_path / "tail")
    with open(tail_trail.path, "a") as handle:
        handle.write('{"entry_uuid": "u-1", "kind": "schema", "from_ver')

    mid_trail = build(tmp_path / "mid")
    lines = mid_trail.path.read_text().splitlines(keepends=True)
    lines[1] = '{"entry_uuid": "u-2", BROKEN}\n'
    mid_trail.path.write_text("".join(lines))

    tail = tail_trail.read()
    mid = mid_trail.read()

    assert tail.status != mid.status
    assert tail.is_usable is True and mid.is_usable is False
    assert tail.status == TRAIL_READ_TRUNCATED_TAIL
    assert mid.status == TRAIL_READ_UNREADABLE


def test_unrecoverable_trailing_fragment_is_unreadable(tmp_path) -> None:
    trail = _trail(tmp_path)
    started = trail.open_step("schema", "1", "2")
    trail.close_step(started, "completed")
    with open(trail.path, "a") as handle:
        handle.write('{"en')
    result = trail.read()
    assert result.status == TRAIL_READ_UNREADABLE
    assert result.corrupt_line_no == 3


def test_line_missing_a_required_field_is_corruption(tmp_path) -> None:
    path = tmp_path / "migration_trail.jsonl"
    good = TrailEntry(
        entry_uuid="u1", kind="schema", status="started",
        started_at="2026-08-18T09:00:00Z",
    ).to_line()
    bad = json.dumps({"entry_uuid": "u2", "kind": "schema"}) + "\n"
    path.write_text(good + bad + good)
    result = read_trail(path)
    assert result.status == TRAIL_READ_UNREADABLE
    assert result.corrupt_line_no == 2


def test_non_utf8_bytes_are_unreadable_not_absent(tmp_path) -> None:
    path = tmp_path / "migration_trail.jsonl"
    path.write_bytes(b"\xff\xfe not utf-8 at all\n")
    result = read_trail(path)
    assert result.status == TRAIL_READ_UNREADABLE


def test_empty_file_is_not_corruption(tmp_path) -> None:
    path = tmp_path / "migration_trail.jsonl"
    path.write_bytes(b"")
    result = read_trail(path)
    assert result.status == TRAIL_READ_OK
    assert result.entries == []


def test_mark_interrupted_appends_and_closes(tmp_path) -> None:
    trail = _trail(tmp_path)
    started = trail.open_step("schema", "1", "2")
    trail.mark_interrupted(started)
    result = trail.read()
    assert [e.status for e in result.entries] == ["started", "interrupted"]
    assert find_unclosed(result.entries) == []
    assert "never recorded an outcome" in result.entries[1].detail


def test_to_line_never_emits_an_embedded_newline(tmp_path) -> None:
    entry = TrailEntry(
        entry_uuid="u1", kind="schema", status="failed",
        started_at="2026-08-18T09:00:00Z",
        error="line one\nline two\nline three",
    )
    line = entry.to_line()
    assert line.count("\n") == 1
    assert line.endswith("\n")
    parsed = json.loads(line)
    assert parsed["error"] == "line one\nline two\nline three"


@pytest.mark.parametrize("value,expected", [(1, 1), (0, 0), (None, None), ("x", None)])
def test_backup_verified_is_tri_valued(value, expected) -> None:
    entry = TrailEntry.from_dict(
        {
            "entry_uuid": "u", "kind": "schema", "status": "completed",
            "started_at": "2026-08-18T09:00:00Z", "backup_verified": value,
        }
    )
    assert entry.backup_verified is expected
