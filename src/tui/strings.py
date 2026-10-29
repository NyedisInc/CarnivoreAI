
from __future__ import annotations

from functools import lru_cache
from typing import Dict

from src.core.notifications.catalog_lines import read_prefixed

PREFIXES = (
    "tui.", "auth.totp_prompt.", "session.status.", "approvals.approved", "approvals.cannot_answer",
    "approvals.col.", "approvals.denied", "approvals.empty", "approvals.failed", "approvals.load_failed",
    "approvals.reason.", "approvals.startup.",
)


@lru_cache(maxsize=1)
def _catalog() -> Dict[str, str]:
    return read_prefixed(PREFIXES)


def t(key: str) -> str:
    return _catalog().get(key, key)
