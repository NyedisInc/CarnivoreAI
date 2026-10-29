
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from src.core.attention.evidence import STATE_NEEDS_USER

HELD_ASK_CAP: int = 512


@dataclass(frozen=True)
class HeldAsk:

    session_id: str
    toast_id: str
    reason: Optional[str]


class AskToasts:

    def __init__(self) -> None:
        self._held: "OrderedDict[str, HeldAsk]" = OrderedDict()

    def hold(self, key: str, session_id: str, toast_id: str, reason: Optional[str]) -> None:
        self._held.pop(key, None)
        self._held[key] = HeldAsk(session_id, toast_id, reason)
        while len(self._held) > HELD_ASK_CAP:
            self._held.popitem(last=False)

    def take_answered(self, key: str, state: str, reason: Optional[str]) -> Optional[HeldAsk]:
        held = self._held.get(key)
        if held is None:
            return None
        if state == STATE_NEEDS_USER and reason == held.reason:
            return None
        return self._held.pop(key)
