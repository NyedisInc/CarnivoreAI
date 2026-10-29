"""Read a pane's screen only when an answer depends on it (#1814).

THE RULE. :func:`decide` answers READ for any of these, in this order, and
SKIP only when none holds:

- ``forced``: a caller about to do something it cannot undo (auto-sleep's
  ``read_fresh``);
- ``codex``: codex writes no status file;
- ``no_record``: no validated record for this instance (absent, stale,
  unreadable, ambiguous). This is the startup gate, the folder-trust dialog
  and the other startup screens, which claude draws before registering;
- ``old_claude``: a record below :data:`MIN_STATUS_FILE_VERSION` or with no
  parseable version, where the waiting contract is not proven;
- ``identity_unproven``: the record's ``procStart`` does not match the pid's
  ``ps`` lstart, or could not be checked (``record_identity``);
- ``waiting``: the record says waiting or names what it waits for;
- ``ask_open``: the watcher's ledger holds a confirmed ``needs_user`` for this
  instance, and only a screen read can prove that ask closed;
- ``needs_user``: the verdict without a screen is ``needs_user`` (a question
  the transcript names), so the dialog is extracted for the approvals list;
- ``transcript_work``: the verdict without a screen is a busy the TRANSCRIPT
  states that a held resting prompt may withdraw, the latching case the
  four-second resting hold exists for;
- ``sticky``: the last read of this pane saw a dialog, a trust or startup
  screen, failed, or saw claude's resting prompt under a withdrawable busy,
  so reading continues every pass until a read comes back plain;
- ``safety_look``: no read of this pane for :data:`SAFETY_LOOK_SECONDS`.

WHAT A SKIP STILL IS. A full observation: the record, the transcript, the
process table and every other tier are read; ``pane``, ``dialog`` and
``startup_screen`` are None, which on this path is what the record itself
states. The resolver is unchanged, so the eight states, ``unknown`` never
being idle and ``status_source`` naming the deciding tier all hold by
construction, and a skipped pass counts as a cycle like any other.
"""

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
from src.core.attention.registry_read import MIN_DELEGATED_BUSY_VERSION, REG_WAITING

MIN_STATUS_FILE_VERSION: Tuple[int, int, int] = MIN_DELEGATED_BUSY_VERSION
SAFETY_LOOK_SECONDS: float = 30.0

READ_FORCED = "forced"
READ_CODEX = "codex"
READ_NO_RECORD = "no_record"
READ_OLD_CLAUDE = "old_claude"
READ_IDENTITY_UNPROVEN = "identity_unproven"
READ_WAITING = "waiting"
READ_ASK_OPEN = "ask_open"
READ_NEEDS_USER = "needs_user"
READ_TRANSCRIPT_WORK = "transcript_work"
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
           seconds_since_read: Optional[float], forced: bool = False) -> ScreenDecision:
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
