
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Mapping, Optional, Sequence

from src.models import Toast

ACK_REASON_DISMISSED = "dismissed"

ACK_REASON_ANSWERED = "answered"

KIND_STOP = "Stop"
KIND_PERMISSION = "PermissionRequest"
KIND_NOTIFICATION = "Notification"

AUTO_ACK_KINDS: Mapping[str, frozenset] = {
    "UserPromptSubmit": frozenset(
        {KIND_STOP, KIND_PERMISSION, KIND_NOTIFICATION}
    ),
    "PreToolUse": frozenset({KIND_PERMISSION}),
    KIND_STOP: frozenset({KIND_PERMISSION, KIND_NOTIFICATION}),
}


def kinds_answered_by(event_kind: str) -> frozenset:
    return AUTO_ACK_KINDS.get(event_kind, frozenset())


def resolve_auto_acks(
    records: Sequence[Toast],
    event_kind: str,
    *,
    cutoff: Optional[datetime] = None,
) -> List[str]:
    kinds = kinds_answered_by(event_kind)
    if not kinds:
        return []
    answered: List[str] = []
    for toast in records or ():
        if toast is None or toast.acknowledged:
            continue
        if toast.kind not in kinds:
            continue
        if cutoff is not None and _raised_after(toast, cutoff):
            continue
        answered.append(toast.id)
    return answered


def _raised_after(toast: Toast, cutoff: datetime) -> bool:
    created = getattr(toast, "created_at", None)
    if created is None:
        return False
    try:
        return created > cutoff
    except TypeError:
        return False


def describe(event_kind: str, acked_ids: Iterable[str]) -> dict:
    return {
        "event_kind": event_kind,
        "answered": len(list(acked_ids)),
        "reason": ACK_REASON_ANSWERED,
    }
