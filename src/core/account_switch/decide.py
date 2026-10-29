
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from src.models.provider_ledger import AccountUsage, UsageWindow

SHORT_MAX_SECONDS = 5 * 3600

MIN_HOURS = 0.1

_KIND_SECONDS = {
    "five_hour": SHORT_MAX_SECONDS,
    "primary": SHORT_MAX_SECONDS,
    "seven_day": 7 * 24 * 3600,
    "seven_day_opus": 7 * 24 * 3600,
    "seven_day_sonnet": 7 * 24 * 3600,
    "secondary": 7 * 24 * 3600,
}


@dataclass(frozen=True)
class SwitchDecision:

    provider: str
    from_account_id: str
    to_account_id: str
    window_kind: str
    used_pct: float
    to_peak_pct: float
    window_seconds: Optional[int] = None


def _length(window: UsageWindow) -> Optional[int]:
    seconds = window.window_seconds
    if isinstance(seconds, int) and seconds > 0:
        return seconds
    return _KIND_SECONDS.get(window.kind)


def _fresh(window: UsageWindow, now: datetime) -> bool:
    return window.resets_at is None or window.resets_at > now


def gating_windows(row: AccountUsage, now: datetime) -> List[UsageWindow]:
    sized = [
        w for w in row.windows if _fresh(w, now) and _length(w) is not None
    ]
    short = [w for w in sized if (_length(w) or 0) <= SHORT_MAX_SECONDS]
    longs = [w for w in sized if (_length(w) or 0) > SHORT_MAX_SECONDS]
    picked: List[UsageWindow] = []
    if short:
        picked.append(max(short, key=lambda w: w.used_pct))
    if longs:
        longest = max(_length(w) or 0 for w in longs)
        picked.append(
            max((w for w in longs if _length(w) == longest), key=lambda w: w.used_pct)
        )
    return picked


def peak(row: AccountUsage, now: datetime) -> Optional[UsageWindow]:
    windows = gating_windows(row, now)
    return max(windows, key=lambda w: w.used_pct) if windows else None


def star_rank(row: AccountUsage, now: datetime) -> Tuple:
    windows = gating_windows(row, now)
    week = next((w for w in windows if (_length(w) or 0) > SHORT_MAX_SECONDS), None)
    if week is None or week.resets_at is None:
        return (1, 0.0, 0.0, 0.0, row.id)
    short = next((w for w in windows if (_length(w) or 0) <= SHORT_MAX_SECONDS), None)
    hours = max((week.resets_at - now).total_seconds() / 3600, MIN_HOURS)
    urgency = (100 - week.used_pct) / hours
    room = 100 - short.used_pct if short is not None else -1.0
    return (0, -urgency, -room, week.resets_at.timestamp(), row.id)


def eligible(row: AccountUsage, now: datetime, threshold_percent: float) -> bool:
    if row.credential_state != "ok":
        return False
    if row.login_expires_at is not None and row.login_expires_at <= now:
        return False
    top = peak(row, now)
    return top is not None and top.used_pct < threshold_percent


def rank_candidates(
    rows: Iterable[AccountUsage],
    *,
    provider: str,
    active_account_id: Optional[str],
    threshold_percent: float,
    now: datetime,
) -> List[AccountUsage]:
    candidates = [
        row
        for row in rows
        if row.provider == provider
        and row.id != active_account_id
        and eligible(row, now, threshold_percent)
    ]
    return sorted(candidates, key=lambda row: star_rank(row, now))


def decide_switch(
    rows: Iterable[AccountUsage],
    *,
    provider: str,
    active_account_id: Optional[str],
    threshold_percent: float,
    now: datetime,
) -> Optional[SwitchDecision]:
    if active_account_id is None:
        return None
    same = [row for row in rows if row.provider == provider]
    active = next((row for row in same if row.id == active_account_id), None)
    if active is None:
        return None
    crossed = [w for w in gating_windows(active, now) if w.used_pct >= threshold_percent]
    if not crossed:
        return None
    trigger = max(crossed, key=lambda w: w.used_pct)
    ranked = rank_candidates(
        same,
        provider=provider,
        active_account_id=active_account_id,
        threshold_percent=threshold_percent,
        now=now,
    )
    if not ranked:
        return None
    chosen = ranked[0]
    chosen_peak = peak(chosen, now)
    return SwitchDecision(
        provider=provider,
        from_account_id=active_account_id,
        to_account_id=chosen.id,
        window_kind=trigger.kind,
        used_pct=trigger.used_pct,
        window_seconds=_length(trigger),
        to_peak_pct=chosen_peak.used_pct if chosen_peak else 0.0,
    )
