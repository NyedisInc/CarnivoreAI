
from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable, Dict, Tuple

from src.core.attention.evidence import REASON_TOOL, STATE_BUSY, STATE_NEEDS_USER, AttentionVerdict

HOLD_SECONDS = 8.0


def beast_handles(session_id: str, observation: Any) -> bool:
    from src.core.approvals.auto_answer import engine as auto_answer, rules
    from src.core.beast_prompts.wiring import would_answer

    if would_answer(session_id, observation):
        return True
    dialog = getattr(getattr(observation, "evidence", None), "dialog", None)
    if dialog is None or getattr(observation, "stale", False) or str(session_id).startswith(("adopted:", "remote:")):
        return False
    policy = auto_answer.grid_policy()
    return any(auto_answer.rule_on(policy, rule.info.id) for rule in rules.rules_for(dialog))


class BeastHold:

    def __init__(self, handles: Callable[[str, Any], bool] = beast_handles, *, clock: Callable[[], float] = time.monotonic,
                 hold_seconds: float = HOLD_SECONDS) -> None:
        self._handles = handles
        self._clock = clock
        self._hold = hold_seconds
        self._since: Dict[str, Tuple[str, float]] = {}

    def mask(self, target: Any, observation: Any) -> AttentionVerdict:
        verdict = observation.verdict
        key = str(target.key)
        dialog = getattr(observation.evidence, "dialog", None)
        try:
            held = verdict.state == STATE_NEEDS_USER and dialog is not None and self._handles(str(target.session_id), observation)
        except (OSError, ValueError, AttributeError):
            held = False
        if not held:
            self._since.pop(key, None)
            return verdict
        fingerprint, first = self._since.get(key, (dialog.fingerprint, self._clock()))
        if fingerprint != dialog.fingerprint:
            first = self._clock()
        self._since[key] = (dialog.fingerprint, first)
        if self._clock() - first >= self._hold:
            return verdict
        return replace(verdict, state=STATE_BUSY, reason=REASON_TOOL, settle_required=False,
                       detail="beast mode will answer this prompt; the alert is held until it does or the deadline passes")
