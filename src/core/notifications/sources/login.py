
from __future__ import annotations

from typing import Dict, Iterable, List

import structlog

from src.core.notifications import contracts
from src.core.notifications.sources import common

logger = structlog.get_logger(__name__)

TYPE_ID = "provider.needs_login"
NEEDS_LOGIN = "needs_login"
_LOGIN_STATES = frozenset({"expired", "missing", "refused"})


def state_word(row: object) -> str:
    poke = getattr(row, "poke", None)
    if row.provider == "claude" and (row.credential_state in _LOGIN_STATES or getattr(poke, "state", None) == NEEDS_LOGIN):
        return NEEDS_LOGIN
    return row.credential_state


class LoginWatch:

    def __init__(self) -> None:
        self._words: Dict[str, str] = {}

    def observe(self, rows: Iterable[object]) -> List[str]:
        fired: List[str] = []
        current = {row.id: state_word(row) for row in rows}
        for row in rows:
            before = self._words.get(row.id)
            if before not in (None, "unknown", NEEDS_LOGIN) and current[row.id] == NEEDS_LOGIN:
                contracts.emit(contracts.NotifyEvent(
                    type_id=TYPE_ID, kind="provider_ledger", title=common.type_title(TYPE_ID), ts=common.now(),
                    severity=contracts.SEVERITY_WARN, session_ref=row.name,
                    instance_key=f"login:{row.id}:{common.now():.0f}",
                ))
                fired.append(row.id)
        self._words = current
        return fired
