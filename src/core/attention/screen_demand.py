
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from src.core.attention.evidence import (
    FAMILY_CODEX,
    REASON_QUEUED_REINVOKE,
    REASON_SUBAGENTS,
    STATE_BUSY,
    STATE_NEEDS_USER,
    TIER_REGISTRY,
    AttentionVerdict,
)
from src.core.attention.registry_record import MIN_DELEGATED_BUSY_VERSION, REG_IDLE, REG_WAITING

MIN_STATUS_FILE_VERSION: Tuple[int, int, int] = MIN_DELEGATED_BUSY_VERSION
SAFETY_LOOK_SECONDS: float = 30.0
TURN_END_LOOK_SECONDS: float = 10.0

READ_FORCED = "forced"
READ_CODEX = "codex"
READ_NO_RECORD = "no_record"
READ_OLD_CLAUDE = "old_claude"
READ_IDENTITY_UNPROVEN = "identity_unproven"
READ_WAITING = "waiting"
READ_ASK_OPEN = "ask_open"
READ_NEEDS_USER = "needs_user"
READ_TRANSCRIPT_WORK = "transcript_work"
READ_TURN_END = "turn_end"
READ_STICKY = "sticky"
READ_SAFETY_LOOK = "safety_look"
SKIP_RECORD = "record_explains_screen"


@dataclass(frozen=True)
class ScreenDecision:

    read: bool
    reason: str


def withdrawable_busy(verdict: AttentionVerdict, registry: Any) -> bool:
    if verdict.state != STATE_BUSY or not verdict.pane_may_veto:
        return False
    confirmed = (verdict.reason in (REASON_SUBAGENTS, REASON_QUEUED_REINVOKE)
                 and bool(getattr(registry, "confirms_background_work", False)))
    return not confirmed


def decide(*, family: Optional[str], registry: Any, identity_proven: Optional[bool],
           ask_open: bool, paneless: AttentionVerdict, sticky: bool,
           seconds_since_read: Optional[float], forced: bool = False,
           seconds_since_status: Optional[float] = None) -> ScreenDecision:
    version = getattr(registry, "version", None)
    checks = (
        (forced, READ_FORCED),
        (family == FAMILY_CODEX, READ_CODEX),
        (not getattr(registry, "known", False), READ_NO_RECORD),
        (version is None or tuple(version) < MIN_STATUS_FILE_VERSION, READ_OLD_CLAUDE),
        (identity_proven is not True, READ_IDENTITY_UNPROVEN),
        (registry.status == REG_WAITING or bool(registry.waiting_for), READ_WAITING),
        (ask_open, READ_ASK_OPEN),
        (paneless.state == STATE_NEEDS_USER, READ_NEEDS_USER),
        (withdrawable_busy(paneless, registry) and paneless.tier != TIER_REGISTRY, READ_TRANSCRIPT_WORK),
        (registry.status == REG_IDLE and seconds_since_status is not None
         and 0 <= seconds_since_status < TURN_END_LOOK_SECONDS, READ_TURN_END),
        (sticky, READ_STICKY),
        (seconds_since_read is None or seconds_since_read >= SAFETY_LOOK_SECONDS, READ_SAFETY_LOOK),
    )
    for holds, reason in checks:
        if holds:
            return ScreenDecision(True, reason)
    return ScreenDecision(False, SKIP_RECORD)


def stays_sticky(*, text: Optional[str], pane: Any, dialog: Any, startup_screen: Any,
                 paneless: AttentionVerdict, registry: Any) -> bool:
    if text is None or dialog is not None or startup_screen is not None:
        return True
    if pane is None:
        return False
    if (getattr(pane, "shows_dialog", False) or getattr(pane, "approval_dialog", False)
            or getattr(pane, "trust_dialog", False)):
        return True
    return pane.resting_prompt is True and withdrawable_busy(paneless, registry)


class ScreenDemand:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: Dict[str, Tuple[float, bool]] = {}

    def since_read(self, session_id: str, now_mono: float) -> Optional[float]:
        with self._lock:
            seen = self._seen.get(session_id)
        return None if seen is None else now_mono - seen[0]

    def sticky(self, session_id: str) -> bool:
        with self._lock:
            seen = self._seen.get(session_id)
        return bool(seen and seen[1])

    def record_read(self, session_id: str, now_mono: float, sticky: bool) -> None:
        with self._lock:
            self._seen[session_id] = (now_mono, sticky)

    def retain_only(self, session_ids: Iterable[str]) -> None:
        live = set(session_ids)
        with self._lock:
            for key in [k for k in self._seen if k not in live]:
                del self._seen[key]
