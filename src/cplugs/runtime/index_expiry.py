
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

GRACE = timedelta(days=2)
REFRESH_INTERVAL_SECONDS = 3600


def _parse(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def index_state(index: Optional[Mapping[str, Any]], now: Optional[datetime] = None) -> str:
    expires = _parse(index.get("expires_at")) if index else None
    if expires is None:
        return "missing"
    now = now or datetime.now(timezone.utc)
    if now <= expires:
        return "fresh"
    return "grace" if now <= expires + GRACE else "expired"


def may_run_third_party(state: str, owner_override: bool = False) -> bool:
    return state in ("fresh", "grace") or owner_override
