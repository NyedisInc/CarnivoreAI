
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pls_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pls_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.provider_ledger import schedule

NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


class TestTheFloorIsPerProvider:

    def test_claude_polls_no_faster_than_every_180_seconds(self):
        assert schedule.floor_seconds("claude") == 180.0

    def test_codex_polls_at_60_seconds_because_its_own_tui_does(self):
        assert schedule.floor_seconds("codex") == 60.0

    def test_a_provider_this_build_does_not_know_gets_the_SLOWEST_floor(self):
        assert schedule.floor_seconds("some-future-provider") == 180.0


class TestJitterIsDeterministicAndBounded:

    def test_the_midpoint_of_the_random_range_moves_nothing(self):
        assert schedule.apply_jitter(180.0, 0.5) == 180.0

    def test_the_bottom_of_the_random_range_is_ten_percent_early(self):
        assert schedule.apply_jitter(180.0, 0.0) == pytest.approx(162.0)

    def test_the_top_of_the_random_range_is_ten_percent_late(self):
        assert schedule.apply_jitter(180.0, 1.0) == pytest.approx(198.0)

    def test_nothing_in_the_range_ever_leaves_the_ten_percent_band(self):
        for step in range(0, 101):
            jittered = schedule.apply_jitter(180.0, step / 100.0)
            assert 162.0 - 1e-9 <= jittered <= 198.0 + 1e-9


class TestASuccessfulPollReturnsToTheFloor:

    def test_an_ok_claude_poll_schedules_the_jittered_floor(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude", state="ok", random_unit=0.5
            )
            == 180.0
        )

    def test_an_ok_codex_poll_schedules_its_own_shorter_floor(self):
        assert (
            schedule.next_interval_seconds(
                provider="codex", state="ok", random_unit=0.5
            )
            == 60.0
        )

    def test_the_floor_carries_the_jitter_it_was_given(self):
        assert schedule.next_interval_seconds(
            provider="claude", state="ok", random_unit=0.0
        ) == pytest.approx(162.0)

    def test_an_ok_poll_DISCARDS_a_rate_limited_backoff_it_was_carrying(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state="ok",
                rate_limited_interval_seconds=1500.0,
                random_unit=0.5,
            )
            == 180.0
        )


class TestALocallyDecidedCredentialStateRechecksFastNotAtTheFloor:

    @pytest.mark.parametrize("state", ["missing", "expired", "refused"])
    def test_a_request_skipped_state_rechecks_at_15_seconds_flat(self, state):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state=state,
                random_unit=0.5,
                request_skipped=True,
            )
            == 15.0
        )

    def test_the_15_second_recheck_ignores_the_random_unit_entirely(self):
        for random_unit in (0.0, 0.5, 1.0):
            assert (
                schedule.next_interval_seconds(
                    provider="claude",
                    state="missing",
                    random_unit=random_unit,
                    request_skipped=True,
                )
                == 15.0
            )

    def test_a_locally_decided_error_still_waits_out_the_floor(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state="error",
                random_unit=0.5,
                request_skipped=True,
            )
            == 180.0
        )

    def test_codex_gets_the_same_15_second_recheck_as_claude(self):
        assert (
            schedule.next_interval_seconds(
                provider="codex",
                state="expired",
                random_unit=0.5,
                request_skipped=True,
            )
            == 15.0
        )


class TestANetworkOutcomeIsNeverFastRecheckedEvenWithTheSameStateName:

    @pytest.mark.parametrize("state", ["missing", "expired", "refused", "error"])
    def test_the_same_four_states_still_get_the_plain_jittered_floor(self, state):
        assert (
            schedule.next_interval_seconds(
                provider="claude", state=state, random_unit=0.5
            )
            == 180.0
        )


class TestTheRateLimitLadder:

    def test_a_retry_after_is_honoured_exactly_as_the_provider_stated_it(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state="rate_limited",
                retry_after_seconds=90.0,
                random_unit=0.0,
            )
            == 90.0
        )

    def test_a_429_with_no_readable_deadline_waits_six_minutes(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude", state="rate_limited", random_unit=0.5
            )
            == 360.0
        )

    def test_a_retry_after_of_zero_is_NOT_permission_to_retry_immediately(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state="rate_limited",
                retry_after_seconds=0.0,
                random_unit=0.5,
            )
            == 360.0
        )

    def test_a_second_consecutive_429_multiplies_the_previous_wait(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state="rate_limited",
                rate_limited_interval_seconds=360.0,
                random_unit=0.5,
            )
            == 540.0
        )

    def test_the_growth_stops_at_thirty_minutes(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state="rate_limited",
                rate_limited_interval_seconds=1500.0,
                random_unit=0.5,
            )
            == 1800.0
        )

    def test_a_longer_retry_after_beats_our_own_backoff(self):
        assert (
            schedule.next_interval_seconds(
                provider="claude",
                state="rate_limited",
                retry_after_seconds=2400.0,
                rate_limited_interval_seconds=360.0,
                random_unit=0.5,
            )
            == 2400.0
        )

    def test_a_codex_429_uses_the_same_ladder_and_not_its_60_second_floor(self):
        assert (
            schedule.next_interval_seconds(
                provider="codex", state="rate_limited", random_unit=0.5
            )
            == 360.0
        )


class TestTheStampTheRowPublishes:

    def test_the_next_poll_is_the_interval_after_now(self):
        assert schedule.next_poll_at(NOW, 180.0) == NOW + timedelta(seconds=180.0)

    def test_it_keeps_the_timezone_it_was_handed(self):
        assert schedule.next_poll_at(NOW, 60.0).tzinfo is not None
