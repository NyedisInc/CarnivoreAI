
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import pipe_liveness as pl

OURS = "/tmp/state/tmux_ext_cloude_demo.pipe"
THEIRS = "/tmp/other/tmux_adopted_cloude_demo.pipe"


def _reading(
    dead: bool = False,
    piped: bool = True,
    activity: int = 1000,
    signature: str = "0:0:0",
    owner: str = OURS,
) -> pl.PaneReading:
    return pl.PaneReading(
        dead=dead,
        piped=piped,
        activity_epoch=activity,
        signature=signature,
        owner=owner,
    )




def test_parse_reads_every_field_off_a_real_tmux_answer():
    raw = "0|1|1789841544|0:10:4|" + OURS + "\n"
    reading = pl.parse_reading(raw)
    assert reading == pl.PaneReading(
        dead=False,
        piped=True,
        activity_epoch=1789841544,
        signature="0:10:4",
        owner=OURS,
    )


def test_parse_keeps_a_path_that_contains_the_separator():
    odd = "/tmp/we|ird/a.pipe"
    reading = pl.parse_reading("0|1|5|0:0:0|" + odd)
    assert reading is not None and reading.owner == odd


def test_parse_refuses_a_short_answer_rather_than_guessing():
    assert pl.parse_reading("0|1|5") is None
    assert pl.parse_reading("") is None


def test_parse_keeps_an_unparseable_activity_as_none_not_zero():
    reading = pl.parse_reading("0|1|not-a-number|0:0:0|" + OURS)
    assert reading is not None and reading.activity_epoch is None


def test_an_absent_option_reads_as_the_empty_string():
    reading = pl.parse_reading("0|1|5|0:0:0|")
    assert reading is not None and reading.owner == ""




def test_a_matching_option_with_the_file_present_is_the_only_skip():
    assert pl.classify_ownership(_reading(), OURS, True) == pl.OWNED


def test_an_absent_option_reissues_even_though_a_copier_is_running():
    verdict = pl.classify_ownership(_reading(owner=""), OURS, True)
    assert verdict == pl.NO_OWNER_RECORDED
    assert verdict in pl.REISSUE_VERDICTS


def test_a_different_option_names_the_thief_and_reissues():
    verdict = pl.classify_ownership(_reading(owner=THEIRS), OURS, True)
    assert verdict == pl.FOREIGN_OWNER
    assert verdict in pl.REISSUE_VERDICTS
    assert verdict in pl.THEFT_VERDICTS


def test_no_copier_at_all_reissues():
    assert pl.classify_ownership(_reading(piped=False), OURS, True) == pl.NO_PIPE


def test_a_missing_file_outranks_a_matching_option():
    verdict = pl.classify_ownership(_reading(), OURS, False)
    assert verdict == pl.FILE_MISSING
    assert verdict in pl.REISSUE_VERDICTS


def test_a_measured_dead_pane_short_circuits_everything():
    verdict = pl.classify_ownership(
        _reading(dead=True, owner=THEIRS), OURS, False
    )
    assert verdict == pl.PANE_DEAD
    assert verdict not in pl.REISSUE_VERDICTS




def _tracker(now: float = 100.0, wall: float = 1000.0) -> pl.SilenceTracker:
    return pl.SilenceTracker(silence_seconds=5.0, now=now, wall_now=wall)


def test_no_viewer_means_no_probe_however_long_the_silence():
    tracker = _tracker()
    assert tracker.due(now=100_000.0, has_viewers=False) is False
    assert tracker.due(now=100_000.0, has_viewers=True) is True


def test_a_watched_pane_is_not_probed_before_the_interval_elapses():
    tracker = _tracker()
    assert tracker.due(now=104.9, has_viewers=True) is False


def test_a_watched_pane_silent_for_the_interval_is_probed():
    assert _tracker().due(now=105.1, has_viewers=True) is True


def test_bytes_arriving_reset_the_silence_clock():
    tracker = _tracker()
    tracker.note_bytes(now=104.0, wall_now=1004.0)
    assert tracker.due(now=105.1, has_viewers=True) is False


def test_two_probes_cannot_run_inside_one_interval():
    tracker = _tracker()
    assert tracker.due(now=106.0, has_viewers=True) is True
    tracker.verdict(_reading(), OURS, now=106.0)
    assert tracker.due(now=107.0, has_viewers=True) is False
    assert tracker.due(now=111.5, has_viewers=True) is True


def test_a_quiet_pane_that_did_not_move_is_left_alone():
    tracker = _tracker(wall=1000.0)
    verdict = tracker.verdict(
        _reading(activity=999, signature="0:0:0"), OURS, now=106.0
    )
    assert verdict == pl.QUIET
    assert verdict not in pl.REISSUE_VERDICTS


def test_activity_newer_than_our_last_byte_is_a_theft_on_the_first_probe():
    tracker = _tracker(wall=1000.0)
    verdict = tracker.verdict(_reading(activity=1004), OURS, now=106.0)
    assert verdict == pl.SILENT_WHILE_PANE_ACTIVE
    assert verdict in pl.THEFT_VERDICTS
    assert verdict in pl.REISSUE_VERDICTS


def test_a_changed_signature_between_two_probes_is_a_theft():
    tracker = _tracker(wall=1000.0)
    first = tracker.verdict(
        _reading(activity=1000, signature="0:10:4"), OURS, now=106.0
    )
    assert first == pl.QUIET
    second = tracker.verdict(
        _reading(activity=1000, signature="0:10:6"), OURS, now=112.0
    )
    assert second == pl.SILENT_WHILE_PANE_ACTIVE


def test_an_unchanged_signature_between_two_probes_stays_quiet():
    tracker = _tracker(wall=1000.0)
    tracker.verdict(_reading(activity=1000, signature="0:10:4"), OURS, now=106.0)
    second = tracker.verdict(
        _reading(activity=1000, signature="0:10:4"), OURS, now=112.0
    )
    assert second == pl.QUIET


def test_bytes_arriving_drop_the_signature_baseline():
    tracker = _tracker(wall=1000.0)
    tracker.verdict(_reading(activity=1000, signature="0:10:4"), OURS, now=106.0)
    tracker.note_bytes(now=107.0, wall_now=1007.0)
    verdict = tracker.verdict(
        _reading(activity=1007, signature="0:10:9"), OURS, now=113.0
    )
    assert verdict == pl.QUIET


def test_a_reading_that_could_not_be_taken_changes_nothing():
    tracker = _tracker()
    assert tracker.verdict(None, OURS, now=106.0) == pl.QUIET


def test_the_tracker_reports_a_foreign_owner_through_the_same_classifier():
    tracker = _tracker()
    verdict = tracker.verdict(_reading(owner=THEIRS), OURS, now=106.0)
    assert verdict == pl.FOREIGN_OWNER


def test_a_dead_pane_never_leaves_a_baseline_behind():
    tracker = _tracker(wall=1000.0)
    tracker.verdict(_reading(signature="0:1:1"), OURS, now=106.0)
    assert tracker.verdict(_reading(dead=True), OURS, now=112.0) == pl.PANE_DEAD
    assert (
        tracker.verdict(_reading(activity=999, signature="0:9:9"), OURS,
                        now=118.0)
        == pl.QUIET
    )


def test_the_option_name_carries_the_deliberate_cloude_spelling():
    assert pl.PIPE_OWNER_OPTION == "@cloude_pipe_path"
    assert pl.PIPE_OWNER_OPTION in pl.OWNERSHIP_FORMAT
