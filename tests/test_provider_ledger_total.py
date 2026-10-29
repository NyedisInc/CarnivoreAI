
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plt_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.provider_ledger.total import compute_total
from src.models.provider_ledger import AccountUsage, UsageWindow

EARLY = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
LATE = datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)


def window(kind: str, used: float, label: str = "5h", resets=None) -> UsageWindow:
    return UsageWindow(kind=kind, label=label, used_pct=used, resets_at=resets)


def account(name: str, *windows: UsageWindow, provider: str = "claude") -> AccountUsage:
    return AccountUsage(
        id=name,
        name=name,
        provider=provider,
        credential_state="ok",
        windows=list(windows),
    )


class TestAnEmptyLedger:

    def test_no_accounts_totals_to_nothing(self):
        total = compute_total([])
        assert total.accounts == 0
        assert total.windows == []

    def test_accounts_that_reported_nothing_still_count_as_accounts(self):
        total = compute_total([account("a"), account("b")])
        assert total.accounts == 2
        assert total.windows == []


class TestTheMean:

    def test_two_accounts_average_rather_than_add(self):
        total = compute_total(
            [
                account("a", window("five_hour", 40.0)),
                account("b", window("five_hour", 60.0)),
            ]
        )
        assert [w.used_pct for w in total.windows] == [50.0]

    def test_an_account_silent_about_a_window_is_not_a_zero(self):
        total = compute_total(
            [
                account("a", window("five_hour", 80.0)),
                account("b", window("seven_day", 10.0, label="7d")),
            ]
        )
        five_hour = [w for w in total.windows if w.kind == "five_hour"][0]
        assert five_hour.used_pct == 80.0
        assert five_hour.accounts == 1

    def test_the_denominator_is_published_per_window(self):
        total = compute_total(
            [
                account("a", window("five_hour", 10.0)),
                account("b", window("five_hour", 20.0)),
                account("c"),
            ]
        )
        assert total.accounts == 3
        assert total.windows[0].accounts == 2

    def test_the_label_comes_from_a_reporting_account(self):
        total = compute_total([account("a", window("seven_day", 5.0, label="7d"))])
        assert total.windows[0].label == "7d"


class TestTheReset:

    def test_the_earliest_reset_wins(self):
        total = compute_total(
            [
                account("a", window("five_hour", 10.0, resets=LATE)),
                account("b", window("five_hour", 20.0, resets=EARLY)),
            ]
        )
        assert total.windows[0].resets_at == EARLY

    def test_a_missing_reset_does_not_win_over_a_real_one(self):
        total = compute_total(
            [
                account("a", window("five_hour", 10.0, resets=None)),
                account("b", window("five_hour", 20.0, resets=LATE)),
            ]
        )
        assert total.windows[0].resets_at == LATE

    def test_no_reset_anywhere_stays_none(self):
        total = compute_total([account("a", window("five_hour", 10.0))])
        assert total.windows[0].resets_at is None

    def test_a_naive_stamp_beside_an_aware_one_does_not_raise(self):
        naive = datetime(2026, 9, 17, 6, 0)
        total = compute_total(
            [
                account("a", window("five_hour", 10.0, resets=naive)),
                account("b", window("five_hour", 20.0, resets=LATE)),
            ]
        )
        assert total.windows[0].resets_at == naive.replace(tzinfo=timezone.utc)


class TestTheOrder:

    def test_known_kinds_come_in_their_declared_order(self):
        rows = [
            account(
                "a",
                window("secondary", 1.0, label="7d"),
                window("seven_day_sonnet", 2.0, label="7d sonnet"),
                window("primary", 3.0),
                window("seven_day", 4.0, label="7d"),
                window("seven_day_opus", 5.0, label="7d opus"),
                window("five_hour", 6.0),
            )
        ]
        assert [w.kind for w in compute_total(rows).windows] == [
            "five_hour",
            "seven_day",
            "seven_day_opus",
            "seven_day_sonnet",
            "primary",
            "secondary",
        ]

    def test_an_unknown_kind_sorts_alphabetically_after_the_known_ones(self):
        rows = [
            account(
                "a",
                window("zzz_new", 1.0),
                window("aaa_new", 2.0),
                window("five_hour", 3.0),
            )
        ]
        assert [w.kind for w in compute_total(rows).windows] == [
            "five_hour",
            "aaa_new",
            "zzz_new",
        ]
