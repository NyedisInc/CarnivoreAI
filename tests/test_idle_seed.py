
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.auto_sleep.idle_seed import (
    ALL_SOURCES,
    SOURCE_CLAUDE_REGISTRY,
    SOURCE_CLAUDE_TRANSCRIPT,
    SOURCE_CODEX_ROLLOUT,
    SOURCE_CODEX_STATUS,
    SOURCE_FALLBACK_NOW,
    pick_idle_seed,
)

NOW = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)


def _before(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


def _after(minutes: float) -> datetime:
    return NOW + timedelta(minutes=minutes)




@pytest.mark.parametrize(
    "source",
    [SOURCE_CLAUDE_REGISTRY, SOURCE_CLAUDE_TRANSCRIPT, SOURCE_CODEX_ROLLOUT, SOURCE_CODEX_STATUS],
)
def test_a_lone_candidate_wins_regardless_of_its_source_label(source):
    result = pick_idle_seed(
        now=NOW, process_started_at=None, candidates=[(_before(90), source)]
    )
    assert result.since == _before(90)
    assert result.source == source
    assert result.clamped_to_process_start is False
    assert result.clamped_to_now is False


def test_the_newest_of_two_claude_candidates_wins():
    result = pick_idle_seed(
        now=NOW,
        process_started_at=None,
        candidates=[
            (_before(120), SOURCE_CLAUDE_REGISTRY),
            (_before(30), SOURCE_CLAUDE_TRANSCRIPT),
        ],
    )
    assert result.since == _before(30)
    assert result.source == SOURCE_CLAUDE_TRANSCRIPT


def test_the_newest_of_two_codex_candidates_wins_the_other_way():
    result = pick_idle_seed(
        now=NOW,
        process_started_at=None,
        candidates=[
            (_before(5), SOURCE_CODEX_ROLLOUT),
            (_before(200), SOURCE_CODEX_STATUS),
        ],
    )
    assert result.since == _before(5)
    assert result.source == SOURCE_CODEX_ROLLOUT


def test_none_candidates_are_ignored_not_compared():
    result = pick_idle_seed(
        now=NOW,
        process_started_at=None,
        candidates=[(None, SOURCE_CLAUDE_REGISTRY), (_before(10), SOURCE_CLAUDE_TRANSCRIPT)],
    )
    assert result.since == _before(10)
    assert result.source == SOURCE_CLAUDE_TRANSCRIPT




def test_a_candidate_older_than_process_start_is_pulled_forward():
    floor = _before(60)
    result = pick_idle_seed(
        now=NOW,
        process_started_at=floor,
        candidates=[(_before(500), SOURCE_CLAUDE_REGISTRY)],
    )
    assert result.since == floor
    assert result.clamped_to_process_start is True
    assert result.source == SOURCE_CLAUDE_REGISTRY


def test_a_candidate_at_or_after_process_start_is_not_clamped():
    floor = _before(60)
    result = pick_idle_seed(
        now=NOW, process_started_at=floor, candidates=[(_before(59), SOURCE_CLAUDE_REGISTRY)]
    )
    assert result.since == _before(59)
    assert result.clamped_to_process_start is False


def test_no_floor_given_skips_the_clamp_entirely():
    result = pick_idle_seed(
        now=NOW, process_started_at=None, candidates=[(_before(10_000), SOURCE_CODEX_ROLLOUT)]
    )
    assert result.since == _before(10_000)
    assert result.clamped_to_process_start is False




def test_a_candidate_newer_than_now_is_pulled_back_to_now():
    result = pick_idle_seed(
        now=NOW, process_started_at=None, candidates=[(_after(5), SOURCE_CLAUDE_TRANSCRIPT)]
    )
    assert result.since == NOW
    assert result.clamped_to_now is True
    assert result.source == SOURCE_CLAUDE_TRANSCRIPT




def test_no_candidates_at_all_falls_back_to_now():
    result = pick_idle_seed(now=NOW, process_started_at=_before(60), candidates=[])
    assert result.since == NOW
    assert result.source == SOURCE_FALLBACK_NOW
    assert result.clamped_to_process_start is False
    assert result.clamped_to_now is False


def test_every_candidate_unreadable_falls_back_to_now():
    result = pick_idle_seed(
        now=NOW,
        process_started_at=None,
        candidates=[(None, SOURCE_CLAUDE_REGISTRY), (None, SOURCE_CLAUDE_TRANSCRIPT)],
    )
    assert result.since == NOW
    assert result.source == SOURCE_FALLBACK_NOW


def test_all_sources_are_exhaustively_named():
    assert ALL_SOURCES == {
        SOURCE_CLAUDE_REGISTRY,
        SOURCE_CLAUDE_TRANSCRIPT,
        SOURCE_CODEX_ROLLOUT,
        SOURCE_CODEX_STATUS,
        SOURCE_FALLBACK_NOW,
    }
