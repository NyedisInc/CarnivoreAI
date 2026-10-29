
from __future__ import annotations

from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core.toast_auto_ack import ACK_REASON_ANSWERED
from src.models import Toast

DEFAULT_HISTORY_LIMIT = 100

MAX_HISTORY_LIMIT = 500


def buckets_from_inbox(inbox: object) -> Mapping[str, Sequence[Toast]]:
    if inbox is None:
        return {}
    return inbox.pending


def collect_toasts(
    buckets: Mapping[str, Sequence[Toast]],
    *,
    unacked_only: bool = False,
) -> List[Toast]:
    flat: List[Toast] = []
    for records in buckets.values():
        if not records:
            continue
        for toast in records:
            if unacked_only and toast.acknowledged:
                continue
            flat.append(toast)
    flat.sort(key=lambda t: (t.created_at, t.id), reverse=True)
    return flat


def clamp_limit(limit: Optional[int], default: int = DEFAULT_HISTORY_LIMIT) -> int:
    if limit is None or limit <= 0:
        limit = default
    return min(limit, MAX_HISTORY_LIMIT)


def page(
    records: Sequence[Toast],
    *,
    limit: int,
    offset: int = 0,
) -> Tuple[List[Toast], int, Optional[int]]:
    if offset < 0:
        offset = 0
    total = len(records)
    items = list(records[offset:offset + limit])
    next_offset = offset + len(items)
    return items, total, (next_offset if next_offset < total else None)


def summarize(records: Iterable[Toast]) -> dict:
    total = 0
    open_count = 0
    answered_count = 0
    by_kind: dict = {}
    for toast in records:
        total += 1
        if not toast.acknowledged:
            open_count += 1
        elif getattr(toast, "ack_reason", None) == ACK_REASON_ANSWERED:
            answered_count += 1
        by_kind[toast.kind] = by_kind.get(toast.kind, 0) + 1
    return {
        "total": total,
        "open": open_count,
        "dismissed": total - open_count,
        "answered": answered_count,
        "by_kind": by_kind,
    }
