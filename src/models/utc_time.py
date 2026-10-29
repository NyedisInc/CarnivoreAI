
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def seconds_since(then: datetime, now: datetime | None = None) -> int:
    current = as_aware_utc(now) if now is not None else utc_now()
    return int((current - as_aware_utc(then)).total_seconds())
