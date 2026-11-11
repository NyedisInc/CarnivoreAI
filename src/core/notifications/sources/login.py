
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List

import structlog

from src.core.notifications import contracts
from src.core.notifications.cards.model import say as cards_say
from src.core.notifications.sources import common

logger = structlog.get_logger(__name__)

TYPE_ID = "provider.needs_login"
NEEDS_LOGIN = "needs_login"
MISSING_GRACE_SECONDS = 120.0
_LOGIN_STATES = frozenset({"refused"})


def reason_key(row: object) -> str:
    deadline = getattr(row, "login_expires_at", None)
    if isinstance(deadline, datetime) and deadline <= datetime.now(timezone.utc):
        return "notify.card.reason.expired"
    if row.credential_state == "missing":
        return "notify.card.reason.missing"
    return "notify.card.reason.refused"


def state_word(row: object) -> str:
    if row.provider != "claude":
        return row.credential_state
    deadline = getattr(row, "login_expires_at", None)
    login_over = isinstance(deadline, datetime) and deadline <= datetime.now(timezone.utc)
    if row.credential_state in _LOGIN_STATES or login_over or getattr(getattr(row, "poke", None), "state", None) == NEEDS_LOGIN:
        return NEEDS_LOGIN
    return row.credential_state


class LoginWatch:

    def __init__(self) -> None:
        self._words: Dict[str, str] = {}
        self._missing_since: Dict[str, float] = {}

    def observe(self, rows: Iterable[object]) -> List[str]:
        fired: List[str] = []
        rows = list(rows)
        now = common.now()
        current = {row.id: state_word(row) for row in rows}
        for row in rows:
            if row.provider != "claude" or current[row.id] != "missing":
                self._missing_since.pop(row.id, None)
                continue
            since = self._missing_since.setdefault(row.id, now)
            if row.id not in self._words or self._words[row.id] == NEEDS_LOGIN or now - since >= MISSING_GRACE_SECONDS:
                current[row.id] = NEEDS_LOGIN
        for row in rows:
            before = self._words.get(row.id)
            if before not in (None, "unknown", NEEDS_LOGIN) and current[row.id] == NEEDS_LOGIN:
                contracts.emit(contracts.NotifyEvent(
                    type_id=TYPE_ID, kind="provider_ledger", title=common.type_title(TYPE_ID), ts=common.now(),
                    severity=contracts.SEVERITY_WARN, session_ref=row.name,
                    instance_key=f"login:{row.id}:{common.now():.0f}",
                    card_hint={"account": row.name, "reason": cards_say(reason_key(row)), "provider": row.provider, "account_id": row.id},
                ))
                fired.append(row.id)
        self._words = current
        return fired
