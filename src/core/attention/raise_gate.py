"""Whether one attention transition may interrupt the user.

THE MUTE BRANCH OF ``hook_toast_gate.py``, AND NOTHING ELSE. The other
two branches of that module, the sub-agent depth gate and the idle-nudge
latch, are DELETED rather than moved: both were guesses about whether a
session was really waiting on the user, made from an in-memory counter
fed by a pane-wide session id that every background agent also posted
under. That counter was wrong nine times in ten (410 of 459 attributable
toasts over a measured 50.8 hours) and no ordering fix could move the
number, because its INPUT was mislabeled at the source. The question
those branches tried to answer is now answered by
:func:`src.core.attention.resolve.resolve_attention` from what the
harness writes to disk, one tier at a time, before a toast is ever
considered. By the time this module is consulted the session has already
been measured as needing the user; the only question left is whether the
user asked not to be told.

So there is ONE gate here, and the rules it carries are the originals.

**Mute covers every toast kind, including ``PermissionRequest``.** The
old sub-agent gate exempted permission prompts because a blocked session
genuinely does want the user. A mute is the user answering that in
advance, for this session, and exempting a kind from it would mean the
control does not do what its label says. A permission-class toast is
therefore never suppressed by ANYTHING except this explicit per-session
mute.

**SUPPRESSING IS NOT ACKNOWLEDGING, and that is the load-bearing half.**
The ledger has already recorded the transition by the time this is
consulted, so a suppressed transition still moves the session's state,
still paints the light, and still flips unread on a ``done_idle``. What
is skipped is the interruption, never the record. A mute that quietly
marked a pending permission answered would strand claude mid-turn behind
a yes/no nobody was told about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

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


def policy_for(reader: Optional[Callable[[Any], Any]], target: Any) -> Any:
    if reader is None:
        return None
    try:
        attached, policy = reader(target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("attention_policy_unreadable", key=target.key, error=str(exc), error_type=type(exc).__name__)
        return None
    return policy if attached else None
