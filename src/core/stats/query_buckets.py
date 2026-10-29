from __future__ import annotations

import functools
import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

class QueryLimit(ValueError):
    pass


def iso_utc(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def minute_window(value) -> tuple[int, int]:
    start = int(value.from_.timestamp()) // 60 * 60
    end = math.ceil(value.to.timestamp() / 60) * 60
    return start, end


@functools.lru_cache(maxsize=1 << 16)
def bucket_of(ts: int, resolution: str, zone: ZoneInfo) -> str:
    local = datetime.fromtimestamp(ts, zone)
    if resolution == "minute":
        local = local.replace(second=0, microsecond=0)
    elif resolution == "5minute":
        local = local.replace(minute=local.minute // 5 * 5, second=0, microsecond=0)
    elif resolution == "hour":
        local = local.replace(minute=0, second=0, microsecond=0)
    elif resolution == "day":
        local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif resolution == "week":
        local = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif resolution == "month":
        local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        local = local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return local.isoformat()


def bucket_bounds(bucket: str, resolution: str, zone: ZoneInfo) -> tuple[int, int]:
    start = datetime.fromisoformat(bucket).astimezone(zone)
    start_ts = int(start.timestamp())
    if resolution == "month":
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    elif resolution == "year":
        end = start.replace(year=start.year + 1)
    elif resolution == "day":
        end = start + timedelta(days=1)
    elif resolution == "week":
        end = start + timedelta(days=7)
    else:
        return start_ts, start_ts + {"minute": 60, "5minute": 300, "hour": 3600}[resolution]
    return start_ts, int(end.timestamp())


def all_buckets(start: int, end: int, resolution: str, zone: ZoneInfo) -> list[str]:
    answer = []
    cursor = start
    while cursor < end:
        bucket = bucket_of(cursor, resolution, zone)
        if not answer or answer[-1] != bucket:
            answer.append(bucket)
            if len(answer) > 600:
                raise QueryLimit("query exceeds 600 points")
        _, bucket_end = bucket_bounds(bucket, resolution, zone)
        cursor = max(cursor + 60, bucket_end)
    return answer


def cell_value(cell: dict, metric: str, resolution: str) -> float | int | None:
    if not cell["count"]:
        return None
    if metric == "quota_utilization":
        return cell["sum"] / cell["count"]
    if metric.startswith("average_"):
        observed = sum(cell["observed_by_minute"].values())
        return cell["sum"] / observed if observed else 0
    return cell["sum"]


def merge_cell(target: dict, cell: dict) -> None:
    target["sum"] += cell["sum"]
    target["count"] += cell["count"]
    target["samples"] += cell["samples"]
    target["unknown"] += cell["unknown"]
    target["sample_minutes"].update(cell["sample_minutes"])
    target["conversations"].update(cell["conversations"])
    for minute, seconds in cell["observed_by_minute"].items():
        target["observed_by_minute"][minute] = max(target["observed_by_minute"].get(minute, 0), seconds)


def empty_cell() -> dict:
    return {"sum": 0, "count": 0, "samples": 0, "unknown": 0, "sample_minutes": set(),
            "observed_by_minute": {}, "conversations": set()}
