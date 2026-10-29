
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

FRESHNESS_CURRENT = "current"
FRESHNESS_STALE = "stale"
FRESHNESS_NEVER_RAN = "never_ran"
FRESHNESS_CANNOT_DETERMINE = "cannot_determine"

DEFAULT_STALE_AFTER_SECONDS = 6 * 3600


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def classify_freshness(
    record: Optional[dict], *, now: Optional[datetime] = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> Tuple[str, Optional[float], str]:
    if record is None:
        return (
            FRESHNESS_NEVER_RAN, None,
            "no liveness artifact on disk: the ingester has not completed a "
            "run in this state directory, or the artifact is unreadable",
        )
    stamp = parse_stamp(record.get("finished_at"))
    if stamp is None:
        return (
            FRESHNESS_CANNOT_DETERMINE, None,
            "liveness artifact carries no parseable finished_at, so its age "
            "cannot be measured",
        )
    reference = now or datetime.now(timezone.utc)
    age = (reference - stamp).total_seconds()
    if age < 0:
        return (
            FRESHNESS_CANNOT_DETERMINE, age,
            f"liveness artifact is stamped {abs(age):.0f}s in the future, so "
            "its age is not a measurement of anything",
        )
    if age <= stale_after_seconds:
        return (
            FRESHNESS_CURRENT, age,
            f"last run completed {age:.0f}s ago, within the "
            f"{stale_after_seconds}s freshness window",
        )
    return (
        FRESHNESS_STALE, age,
        f"last run completed {age:.0f}s ago, past the "
        f"{stale_after_seconds}s freshness window",
    )
