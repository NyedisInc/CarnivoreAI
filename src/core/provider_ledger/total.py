
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from src.models.provider_ledger import (
    AccountUsage,
    LedgerTotal,
    LedgerTotalWindow,
    UsageWindow,
)

KIND_ORDER: Tuple[str, ...] = (
    "five_hour",
    "seven_day",
    "seven_day_opus",
    "seven_day_sonnet",
    "primary",
    "secondary",
)


def compute_total(accounts: List[AccountUsage], identity_keys: Optional[Dict[str, Optional[str]]] = None) -> LedgerTotal:
    keys = identity_keys or {}
    seen: Set[str] = set()
    counted: List[AccountUsage] = []
    for account in accounts:
        key = keys.get(account.id)
        if key:
            if key in seen:
                continue
            seen.add(key)
        counted.append(account)
    accounts = counted
    buckets: Dict[str, List[UsageWindow]] = {}
    for account in accounts:
        for window in account.windows:
            buckets.setdefault(window.kind, []).append(window)

    windows: List[LedgerTotalWindow] = []
    for kind in sorted(buckets, key=_position):
        reporting = buckets[kind]
        windows.append(
            LedgerTotalWindow(
                kind=kind,
                label=reporting[0].label,
                used_pct=sum(w.used_pct for w in reporting) / len(reporting),
                resets_at=_earliest_reset(reporting),
                accounts=len(reporting),
            )
        )
    return LedgerTotal(accounts=len(accounts), windows=windows)


def _position(kind: str) -> Tuple[int, str]:
    if kind in KIND_ORDER:
        return (KIND_ORDER.index(kind), "")
    return (len(KIND_ORDER), kind)


def _earliest_reset(windows: List[UsageWindow]) -> Optional[datetime]:
    stamps = [
        w.resets_at if w.resets_at.tzinfo else w.resets_at.replace(tzinfo=timezone.utc)
        for w in windows
        if w.resets_at is not None
    ]
    if not stamps:
        return None
    return min(stamps)
