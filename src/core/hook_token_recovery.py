
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "RECOVERY_ACCEPTED",
    "RECOVERY_NO_MATCH",
    "RECOVERY_UNAVAILABLE",
    "SUPERSEDED_RING_SIZE",
    "RecoveryDecision",
    "SupersededHookTokens",
]

RECOVERY_ACCEPTED = "accepted"

RECOVERY_NO_MATCH = "no_match"

RECOVERY_UNAVAILABLE = "unavailable"

SUPERSEDED_RING_SIZE = 4


@dataclass(frozen=True)
class RecoveryDecision:

    outcome: str
    token: Optional[str] = None
    tmux_name: Optional[str] = None

    @property
    def accepted(self) -> bool:
        return self.outcome == RECOVERY_ACCEPTED


class SupersededHookTokens:

    def __init__(self, ring_size: int = SUPERSEDED_RING_SIZE) -> None:
        if ring_size < 1:
            raise ValueError("ring_size must be at least 1")
        self._ring_size = ring_size
        self._rings: Dict[str, List[Tuple[str, Optional[str]]]] = {}

    def record(
        self,
        session_id: str,
        token: str,
        *,
        tmux_name: Optional[str],
    ) -> None:
        if not session_id or not token:
            return
        entries = self._rings.setdefault(session_id, [])
        entries[:] = [e for e in entries if e[0] != token]
        entries.append((token, tmux_name))
        if len(entries) > self._ring_size:
            del entries[: len(entries) - self._ring_size]

    def decide(
        self,
        session_id: str,
        presented: str,
        *,
        current_tmux_name: Optional[str],
    ) -> RecoveryDecision:
        """Judge a token the ordinary validation has already rejected.

        Description: pure with respect to the caller's state - it reads
          the ring and answers, changing nothing. ``consume`` is the
          separate step that applies the decision, so a caller that
          decides not to act leaves the ring untouched.

          The pane scope is a REFUSAL, not a relaxation: an entry whose
          recorded tmux name disagrees with the name currently bound to
          the id describes a different pane and is skipped. An unknown
          binding on either side yields ``RECOVERY_UNAVAILABLE``, because
          a check that could not be scoped is not a check that passed.
        Inputs: session_id (str). presented (str) - the token from the
          request header. current_tmux_name (str | None) - the name the
          store currently binds to this id.
        Output: RecoveryDecision.
        Example: ring.decide('ses_a', tok, current_tmux_name='cloude_a')
        """
        if not session_id or not presented:
            return RecoveryDecision(RECOVERY_UNAVAILABLE)
        entries = self._rings.get(session_id)
        if not entries:
            return RecoveryDecision(RECOVERY_UNAVAILABLE)
        if not current_tmux_name:
            return RecoveryDecision(RECOVERY_UNAVAILABLE)

        scoped = [e for e in entries if e[1] == current_tmux_name]
        if not scoped:
            return RecoveryDecision(
                RECOVERY_UNAVAILABLE, tmux_name=current_tmux_name
            )

        for token, name in scoped:
            try:
                match = hmac.compare_digest(token, presented)
            except (TypeError, ValueError):
                match = False
            if match:
                return RecoveryDecision(
                    RECOVERY_ACCEPTED, token=token, tmux_name=name
                )
        return RecoveryDecision(
            RECOVERY_NO_MATCH, tmux_name=current_tmux_name
        )

    def consume(self, session_id: str, token: str) -> bool:
        entries = self._rings.get(session_id)
        if not entries:
            return False
        remaining = [e for e in entries if e[0] != token]
        removed = len(remaining) != len(entries)
        if remaining:
            entries[:] = remaining
        else:
            self._rings.pop(session_id, None)
        return removed

    def forget(self, session_id: str) -> None:
        self._rings.pop(session_id, None)

    def size(self, session_id: str) -> int:
        return len(self._rings.get(session_id) or ())
