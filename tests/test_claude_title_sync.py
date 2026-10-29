
from __future__ import annotations

import json

import pytest

from src.core.claude_title_sync import (
    CUSTOM_TITLE_FOUND,
    CUSTOM_TITLE_NO_RECORD,
    CUSTOM_TITLE_UNREADABLE,
    DEFAULT_TAIL_BYTES,
    TITLE_APPLIED,
    TITLE_BASELINE_RECORDED,
    TITLE_NOT_MEASURED,
    TITLE_UNCHANGED,
    CustomTitleRead,
    decide_title_application,
    read_newest_custom_title,
    read_tail_records,
)

SESSION_UUID = "916c846d-db44-472a-8e50-65999798ee3c"


def _title_record(name: str) -> str:
    return json.dumps(
        {
            "type": "custom-title",
            "customTitle": name,
            "sessionId": SESSION_UUID,
        }
    )


def _noise_record(kind: str) -> str:
    return json.dumps(
        {
            "type": kind,
            "sessionId": SESSION_UUID,
            "timestamp": "2026-09-08T14:55:30.247Z",
        }
    )


def _write(tmp_path, lines, name="transcript.jsonl"):
    target = tmp_path / name
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(target)




def test_reads_the_newest_of_several_title_records(tmp_path):
    path = _write(
        tmp_path,
        [
            _title_record("First Name"),
            _noise_record("assistant"),
            _title_record("Second Name"),
            _noise_record("user"),
            _title_record("Third Name"),
            _noise_record("mode"),
        ],
    )

    read = read_newest_custom_title(path)

    assert read.status == CUSTOM_TITLE_FOUND
    assert read.title == "Third Name"
    assert read.found is True


def test_a_transcript_with_no_title_record_reports_no_record(tmp_path):
    path = _write(
        tmp_path,
        [
            _noise_record("queue-operation"),
            _noise_record("user"),
            _noise_record("assistant"),
            _noise_record("agent-name"),
            _noise_record("mode"),
            _noise_record("permission-mode"),
            _noise_record("last-prompt"),
        ],
    )

    read = read_newest_custom_title(path)

    assert read.status == CUSTOM_TITLE_NO_RECORD
    assert read.title is None
    assert read.found is False


def test_an_unreadable_path_is_a_named_outcome_not_an_exception(tmp_path):
    read = read_newest_custom_title(str(tmp_path / "does-not-exist.jsonl"))

    assert read.status == CUSTOM_TITLE_UNREADABLE
    assert read.found is False
    assert read.detail


def test_a_none_path_is_unreadable_rather_than_empty():
    read = read_newest_custom_title(None)

    assert read.status == CUSTOM_TITLE_UNREADABLE
    assert read.found is False


def test_a_directory_in_place_of_a_transcript_is_unreadable(tmp_path):
    read = read_newest_custom_title(str(tmp_path))

    assert read.status == CUSTOM_TITLE_UNREADABLE


def test_a_malformed_line_is_skipped_and_the_good_one_still_reads(tmp_path):
    target = tmp_path / "partial.jsonl"
    target.write_text(
        _title_record("Good Name") + "\n" + '{"type":"custom-ti',
        encoding="utf-8",
    )

    read = read_newest_custom_title(str(target))

    assert read.status == CUSTOM_TITLE_FOUND
    assert read.title == "Good Name"


def test_a_title_record_with_a_blank_name_is_not_a_title(tmp_path):
    path = _write(
        tmp_path,
        [
            _title_record("Real Name"),
            json.dumps(
                {"type": "custom-title", "customTitle": "   ", "sessionId": SESSION_UUID}
            ),
        ],
    )

    read = read_newest_custom_title(path)

    assert read.status == CUSTOM_TITLE_FOUND
    assert read.title == "Real Name"




def test_the_read_is_bounded_and_never_scans_the_whole_file(tmp_path):
    filler = [_noise_record("assistant") for _ in range(3000)]
    path = _write(tmp_path, filler + [_title_record("Tail Name")])

    read = read_newest_custom_title(path)

    assert read.status == CUSTOM_TITLE_FOUND
    assert read.title == "Tail Name"
    assert read.file_size > DEFAULT_TAIL_BYTES
    assert read.scanned_from <= read.file_size - DEFAULT_TAIL_BYTES
    assert read.file_size - read.scanned_from <= 2 * DEFAULT_TAIL_BYTES


def test_a_title_older_than_the_window_reads_as_no_record(tmp_path):
    filler = [_noise_record("assistant") for _ in range(3000)]
    path = _write(tmp_path, [_title_record("Ancient Name")] + filler)

    read = read_newest_custom_title(path)

    assert read.status == CUSTOM_TITLE_NO_RECORD


def test_an_offset_only_ever_moves_the_start_forward(tmp_path):
    path = _write(tmp_path, [_title_record("Only Name")])
    size = read_newest_custom_title(path).file_size

    read = read_newest_custom_title(path, from_offset=size)

    assert read.scanned_from == size
    assert read.status == CUSTOM_TITLE_NO_RECORD


def test_an_offset_past_a_truncated_file_is_clamped(tmp_path):
    path = _write(tmp_path, [_title_record("Only Name")])

    read = read_newest_custom_title(path, from_offset=10_000_000)

    assert read.status == CUSTOM_TITLE_NO_RECORD
    assert read.scanned_from == read.file_size




def _fat_record(kind: str, payload_bytes: int) -> str:
    return json.dumps({"type": kind, "plan": "p" * payload_bytes})


def test_a_record_wider_than_the_window_is_read_rather_than_dropped(tmp_path):
    path = _write(tmp_path, [_noise_record("user"), _fat_record("assistant", 40_000)])

    read = read_tail_records(path, tail_bytes=32 * 1024)

    assert read.readable
    assert [record["type"] for record in read.records] == ["assistant"]
    assert len(read.records[-1]["plan"]) == 40_000


def test_the_backward_scan_for_a_boundary_is_itself_bounded(tmp_path):
    path = _write(tmp_path, [_fat_record("assistant", 200_000)])

    read = read_tail_records(path, tail_bytes=32 * 1024)

    assert read.readable
    assert read.records == ()
    assert read.file_size - read.scanned_from <= 2 * 32 * 1024


def test_a_window_that_opens_on_a_boundary_keeps_that_whole_record(tmp_path):
    rows = [_noise_record("user") for _ in range(40)]
    path = _write(tmp_path, rows)
    per_record = len(rows[0]) + 1

    read = read_tail_records(path, tail_bytes=per_record * 10)

    assert read.readable
    assert len(read.records) == 10


def test_an_incremental_read_does_not_lose_the_first_new_record(tmp_path):
    path = _write(tmp_path, [_noise_record("user")])
    consumed = read_tail_records(path).file_size

    with open(path, "a", encoding="utf-8") as handle:
        handle.write(_title_record("Renamed Here") + "\n")
        handle.write(_noise_record("assistant") + "\n")

    read = read_tail_records(path, from_offset=consumed)

    assert [record["type"] for record in read.records] == [
        "custom-title",
        "assistant",
    ]
    title = read_newest_custom_title(path, from_offset=consumed)
    assert (title.status, title.title) == (CUSTOM_TITLE_FOUND, "Renamed Here")




def _found(title):
    return CustomTitleRead(CUSTOM_TITLE_FOUND, title=title, file_size=1, scanned_from=0)


def test_first_sight_of_a_title_is_a_baseline_and_moves_nothing():
    verdict = decide_title_application(
        _found("Typed Days Ago"),
        current_title="Set In The Browser",
        recorded_claude_title=None,
    )

    assert verdict.action == TITLE_BASELINE_RECORDED
    assert verdict.title == "Typed Days Ago"
    assert verdict.writes_visible_title is False


def test_a_title_that_changed_after_the_baseline_is_applied():
    verdict = decide_title_application(
        _found("New Name"),
        current_title="Old Name",
        recorded_claude_title="Old Name",
    )

    assert verdict.action == TITLE_APPLIED
    assert verdict.title == "New Name"
    assert verdict.writes_visible_title is True


def test_the_same_event_twice_writes_nothing_the_second_time():
    first = decide_title_application(
        _found("New Name"),
        current_title="Old Name",
        recorded_claude_title="Old Name",
    )
    assert first.action == TITLE_APPLIED

    second = decide_title_application(
        _found("New Name"),
        current_title=first.title,
        recorded_claude_title=first.title,
    )

    assert second.action == TITLE_UNCHANGED
    assert second.writes_visible_title is False


def test_a_read_that_did_not_answer_decides_nothing():
    verdict = decide_title_application(
        CustomTitleRead(CUSTOM_TITLE_UNREADABLE, detail="gone"),
        current_title="Whatever",
        recorded_claude_title="Whatever",
    )

    assert verdict.action == TITLE_NOT_MEASURED
    assert verdict.writes_visible_title is False


def test_no_record_decides_nothing_either():
    verdict = decide_title_application(
        CustomTitleRead(CUSTOM_TITLE_NO_RECORD, detail="nothing in the window"),
        current_title="Whatever",
        recorded_claude_title=None,
    )

    assert verdict.action == TITLE_NOT_MEASURED


def test_a_browser_rename_whose_push_landed_records_without_reannouncing():
    verdict = decide_title_application(
        _found("Browser Name"),
        current_title="Browser Name",
        recorded_claude_title="Older Name",
    )

    assert verdict.action == TITLE_APPLIED
    assert verdict.writes_visible_title is False


def test_a_stale_claude_title_does_not_clobber_a_newer_browser_label():
    verdict = decide_title_application(
        _found("Stale Claude Name"),
        current_title="Fresh Browser Label",
        recorded_claude_title="Stale Claude Name",
    )

    assert verdict.action == TITLE_UNCHANGED
    assert verdict.writes_visible_title is False


@pytest.mark.parametrize("recorded", ["", "   ", None])
def test_a_blank_recorded_marker_counts_as_never_recorded(recorded):
    verdict = decide_title_application(
        _found("Some Name"),
        current_title="Label",
        recorded_claude_title=recorded,
    )

    assert verdict.action == TITLE_BASELINE_RECORDED
