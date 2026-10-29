
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

from src.core.session_activity import (
    EVENT_NOTIFICATION,
    EVENT_PERMISSION_REQUEST,
    EVENT_STOP,
)

logger = structlog.get_logger()

SUPPRESSED_NOTIFICATIONS_MUTED: str = "notifications_muted"

LOG_MUTED: str = "attention_toast_suppressed_notifications_muted"

TOAST_KINDS: frozenset = frozenset(
    {EVENT_STOP, EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST}
)


@dataclass(frozen=True)
class RaiseVerdict:

    suppressed_by: Optional[str] = None

    log_event: Optional[str] = None

    log_fields: Dict[str, Any] = field(default_factory=dict)

    @property
    def raises_toast(self) -> bool:
        return self.suppressed_by is None


def resolve_raise(
    kind: str, *, policy_store_attached: bool, policy: Any
) -> RaiseVerdict:
    if policy_store_attached and (policy is None or policy.suppresses):
        return RaiseVerdict(
            suppressed_by=SUPPRESSED_NOTIFICATIONS_MUTED,
            log_event=LOG_MUTED,
            log_fields={
                "policy": getattr(policy, "verdict", "unreadable"),
                "policy_generation": getattr(policy, "generation", None),
                "toast_kind": kind,
            },
        )
    return RaiseVerdict()


def policy_for(reader: Optional[Callable[[Any], Tuple[bool, Any]]], target: Any) -> Tuple[bool, Any]:
    if reader is None:
        return False, None
    try:
        attached, policy = reader(target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("attention_policy_unreadable", key=target.key, error=str(exc), error_type=type(exc).__name__)
        return True, None
    return bool(attached), (policy if attached else None)
