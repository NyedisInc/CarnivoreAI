
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.db_models import SESSION_LIFECYCLE_SOURCE_IMPORT

RECENT_NEWEST_CLOSED_FIRST: bool = True

BASIS_CLOSED = "closed"
BASIS_LAST_ACTIVE = "last_active"
BASIS_ADDED = "added"


def parse_stamp(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _latest(row: Mapping[str, Any], columns: Tuple[str, ...]) -> Optional[str]:
    best: Optional[Tuple[datetime, str]] = None
    for column in columns:
        raw = row.get(column)
        parsed = parse_stamp(raw)
        if parsed is not None and (best is None or parsed > best[0]):
            best = (parsed, str(raw))
    return best[1] if best else None


def closed_time(row: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    if row.get("lifecycle_source") != SESSION_LIFECYCLE_SOURCE_IMPORT:
        stamp = row.get("lifecycle_checked_at")
        if parse_stamp(stamp) is not None:
            return str(stamp), BASIS_CLOSED
    active = _latest(row, ("last_work_at", "last_seen_running_at"))
    if active:
        return active, BASIS_LAST_ACTIVE
    added = _latest(row, ("created_at", "lifecycle_checked_at"))
    if added:
        return added, BASIS_ADDED
    return None, None


def order_recent(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    floor = datetime.min.replace(tzinfo=timezone.utc)
    stamped = [(closed_time(row)[0], row) for row in rows]
    known = [(parse_stamp(s), r) for s, r in stamped if parse_stamp(s) is not None]
    unknown = [r for s, r in stamped if parse_stamp(s) is None]
    known.sort(key=lambda pair: pair[0] or floor, reverse=RECENT_NEWEST_CLOSED_FIRST)
    return [r for _, r in known] + unknown
