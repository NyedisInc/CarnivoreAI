
from __future__ import annotations

import os
import pwd
import re
from datetime import datetime, timezone
from typing import Callable, Iterable, List, Optional, Protocol, Sequence, TypeVar

import structlog

logger = structlog.get_logger()

_ACCOUNT_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

CLAUDE_FALLBACK_ACCOUNT = "claude-code-user"


class _Expiring(Protocol):

    expires_at: Optional[datetime]
    source: str


_C = TypeVar("_C", bound=_Expiring)


def claude_keychain_account() -> str:
    name = os.environ.get("USER")
    if not name:
        try:
            name = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            name = None
    if not name or not _ACCOUNT_NAME_RE.match(name):
        return CLAUDE_FALLBACK_ACCOUNT
    return name


def _freshness(candidate: _Expiring) -> datetime:
    if candidate.expires_at is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return candidate.expires_at


def pick_freshest(candidates: Sequence[Optional[_C]]) -> Optional[_C]:
    chosen: Optional[_C] = None
    for candidate in candidates:
        if candidate is None:
            continue
        if chosen is None or _freshness(candidate) > _freshness(chosen):
            chosen = candidate
    return chosen


def is_live(candidate: Optional[_Expiring], now: datetime) -> bool:
    if candidate is None:
        return False
    return candidate.expires_at is None or candidate.expires_at > now


def read_freshest(
    services: Iterable[str],
    read_keychain: Callable[[str, Optional[str]], Optional[_C]],
    read_file: Callable[[], Optional[_C]],
    now: datetime,
) -> Optional[_C]:
    account = claude_keychain_account()
    found: List[Optional[_C]] = []
    for service in services:
        own = read_keychain(service, account)
        found.append(own)
        if not is_live(own, now):
            found.append(read_keychain(service, None))
    found.append(read_file())

    chosen = pick_freshest(found)
    if chosen is not None:
        readings = [c for c in found if c is not None]
        logger.debug(
            "claude_credential_store_chosen",
            source=chosen.source,
            readings=len(readings),
            passed_over_lapsed=any(not is_live(c, now) for c in readings),
        )
    return chosen
