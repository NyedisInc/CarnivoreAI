
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import List, Optional

from src.config.provider_account_switch import (
    DEFAULT_THRESHOLD_PERCENT,
    ProviderAccountSwitchConfig,
)
from src.config.provider_accounts import ProviderAccount
from src.core.account_switch.auto_switch import plan_switches
from src.core.account_switch.decide import decide_switch, eligible, rank_candidates
from src.models.provider_ledger import (
    AccountUsage,
    LedgerSnapshot,
    LedgerTotal,
    LoopStatus,
    UsageWindow,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def row(
    account_id: str,
    provider: str = "claude",
    short: Optional[float] = 10.0,
    week: Optional[float] = 10.0,
    state: str = "ok",
    login_expires_at: Optional[datetime] = None,
    resets_in: timedelta = timedelta(hours=2),
) -> AccountUsage:
    windows: List[UsageWindow] = []
    if short is not None:
        windows.append(UsageWindow(
            kind="five_hour", label="5h", used_pct=short,
            window_seconds=18000, resets_at=NOW + resets_in,
        ))
    if week is not None:
        windows.append(UsageWindow(
            kind="seven_day", label="7d", used_pct=week,
            window_seconds=604800, resets_at=NOW + timedelta(days=3),
        ))
    return AccountUsage(
        id=account_id, name=account_id, provider=provider,
        credential_state=state, windows=windows,
        login_expires_at=login_expires_at,
    )


def decide(rows, active="a", threshold=90, provider="claude"):
    return decide_switch(
        rows, provider=provider, active_account_id=active,
        threshold_percent=threshold, now=NOW,
    )




def test_a_codex_account_is_never_a_candidate_for_the_claude_pointer():
    rows = [row("a", short=95), row("x", provider="codex", short=0, week=0)]
    assert decide(rows) is None


def test_a_claude_account_is_chosen_when_one_exists_beside_the_codex_one():
    rows = [
        row("a", short=95),
        row("x", provider="codex", short=0, week=0),
        row("b", short=20, week=20),
    ]
    decision = decide(rows)
    assert decision is not None
    assert (decision.provider, decision.from_account_id, decision.to_account_id) == ("claude", "a", "b")


def test_the_codex_pointer_rotates_among_codex_accounts_only():
    rows = [
        row("c1", provider="codex", week=99, short=None),
        row("b", provider="claude", short=0, week=0),
        row("c2", provider="codex", week=30, short=None),
    ]
    decision = decide(rows, active="c1", provider="codex")
    assert decision is not None and decision.to_account_id == "c2"




def test_an_expired_or_unchecked_login_is_never_chosen():
    for state in ("expired", "missing", "refused", "error", "rate_limited", "unknown"):
        rows = [row("a", short=95), row("b", short=0, week=0, state=state)]
        assert decide(rows) is None, state


def test_a_login_past_its_own_expiry_is_never_chosen():
    rows = [row("a", short=95), row("b", short=0, week=0, login_expires_at=NOW - timedelta(minutes=1))]
    assert decide(rows) is None


def test_an_account_with_no_reading_is_never_chosen():
    rows = [row("a", short=95), row("b", short=None, week=None)]
    assert decide(rows) is None




def test_below_the_threshold_nothing_moves():
    rows = [row("a", short=89.9, week=50), row("b", short=0, week=0)]
    assert decide(rows) is None


def test_at_the_threshold_the_short_window_triggers():
    decision = decide([row("a", short=90, week=10), row("b", short=5, week=5)])
    assert decision is not None
    assert (decision.window_kind, decision.used_pct) == ("five_hour", 90)


def test_the_weekly_window_triggers_on_its_own():
    decision = decide([row("a", short=5, week=97), row("b", short=5, week=5)])
    assert decision is not None and decision.window_kind == "seven_day"


def test_a_candidate_at_or_over_the_threshold_is_not_a_target():
    rows = [row("a", short=95), row("b", short=91, week=10)]
    assert decide(rows) is None


def test_a_window_past_its_own_reset_does_not_trigger():
    rows = [row("a", short=99, week=10, resets_in=timedelta(minutes=-5)), row("b", short=0, week=0)]
    assert decide(rows) is None


def test_a_custom_threshold_is_honoured():
    rows = [row("a", short=75, week=10), row("b", short=0, week=0)]
    assert decide(rows, threshold=90) is None
    assert decide(rows, threshold=70) is not None




def test_the_most_weekly_left_per_hour_to_its_reset_wins():
    rows = [
        row("a", short=95),
        row("b", short=40, week=10),
        row("c", short=10, week=30),
        row("d", short=60, week=5),
    ]
    decision = decide(rows)
    assert decision is not None and decision.to_account_id == "d"


def _windows(spec) -> List[UsageWindow]:
    return [
        UsageWindow(kind=kind, label=kind, used_pct=used, window_seconds=seconds,
                    resets_at=FIX_NOW + timedelta(hours=hours))
        for kind, used, seconds, hours in spec
    ]


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "account_switch_star_parity.json").read_text()
)
FIX_NOW = datetime.fromisoformat(FIXTURE["now"].replace("Z", "+00:00"))


def test_the_screenshot_case_switches_to_the_starred_account():
    rows = [
        AccountUsage(id="claude-code-larkspur", name="Larkspur", provider="claude",
                     credential_state="ok",
                     windows=_windows([["five_hour", 10, 18000, 2], ["seven_day", 99, 604800, 30]])),
        AccountUsage(id="claude-code-acme", name="Acme", provider="claude", credential_state="ok",
                     windows=_windows([["five_hour", 0, 18000, 4], ["seven_day", 0, 604800, 150]])),
        AccountUsage(id="claude-code-dgai", name="DGAI", provider="claude", credential_state="ok",
                     windows=_windows([["five_hour", 0, 18000, 4], ["seven_day", 0, 604800, 140]])),
        AccountUsage(id="claude-code-beta", name="Beta", provider="claude", credential_state="ok",
                     windows=_windows([["five_hour", 0, 18000, 3], ["seven_day", 8, 604800, 20]])),
    ]
    decision = decide_switch(rows, provider="claude", active_account_id="claude-code-larkspur",
                             threshold_percent=99, now=FIX_NOW)
    assert decision is not None
    assert decision.to_account_id == "claude-code-beta"


def test_the_switch_ranks_every_parity_case_as_the_star_does():
    for case in FIXTURE["cases"]:
        rows = [
            AccountUsage(id=a["id"], name=a["id"], provider="claude", credential_state="ok",
                         windows=_windows(a["windows"]))
            for a in case["accounts"]
        ]
        ranked = rank_candidates(rows, provider="claude", active_account_id=None,
                                 threshold_percent=99, now=FIX_NOW)
        assert [r.id for r in ranked] == case["order"], case["name"]


def test_no_active_account_means_no_switch():
    assert decide([row("b", short=0)], active=None) is None


def test_eligible_reads_the_same_three_conditions():
    assert eligible(row("b", short=10), NOW, 90) is True
    assert eligible(row("b", short=95), NOW, 90) is False
    assert eligible(row("b", short=10, state="expired"), NOW, 90) is False




def test_auto_switch_is_off_by_default_and_the_threshold_is_ninety_nine():
    switch = ProviderAccountSwitchConfig()
    assert switch.auto_switch is False
    assert switch.threshold_percent == DEFAULT_THRESHOLD_PERCENT == 99
    assert switch.active_claude is None and switch.active_codex is None


def _snapshot(rows):
    return LedgerSnapshot(accounts=rows, total=LedgerTotal(accounts=len(rows)), loop=LoopStatus(alive=True))


def _accounts():
    return [
        ProviderAccount(id="a", name="A", provider="claude", claude_config_dir="/p/a"),
        ProviderAccount(id="b", name="B", provider="claude", claude_config_dir="/p/b"),
    ]


def test_with_auto_switch_off_the_planner_moves_nothing_even_past_the_threshold():
    snap = _snapshot([row("a", short=99.5), row("b", short=0, week=0)])
    off = ProviderAccountSwitchConfig(active_claude="a")
    assert plan_switches(snap, _accounts(), off, now=NOW, linkable=lambda _a: True) == []
    on = ProviderAccountSwitchConfig(auto_switch=True, active_claude="a")
    moved = plan_switches(snap, _accounts(), on, now=NOW, linkable=lambda _a: True)
    assert [(d.from_account_id, d.to_account_id) for d in moved] == [("a", "b")]


def test_a_target_that_cannot_resume_is_skipped_for_the_next_best():
    accounts = _accounts() + [
        ProviderAccount(id="c", name="C", provider="claude", claude_config_dir="/p/c"),
    ]
    snap = _snapshot([row("a", short=99.5), row("b", short=0, week=0), row("c", short=30, week=30)])
    on = ProviderAccountSwitchConfig(auto_switch=True, active_claude="a")
    moved = plan_switches(snap, accounts, on, now=NOW, linkable=lambda acct: acct.id != "b")
    assert [d.to_account_id for d in moved] == ["c"]


def test_rank_candidates_is_the_order_the_rule_would_pick_in():
    rows = [row("a", short=95), row("b", short=40), row("c", short=20), row("d", state="expired"),
            row("x", provider="codex", short=1)]
    ranked = rank_candidates(rows, provider="claude", active_account_id="a",
                             threshold_percent=90, now=NOW)
    assert [r.id for r in ranked] == ["c", "b"]
    best = decide_switch(rows, provider="claude", active_account_id="a",
                         threshold_percent=90, now=NOW)
    assert best is not None and best.to_account_id == ranked[0].id
