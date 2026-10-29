
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.core.session_status_seed_records import parse_timestamp

USAGE_LIMIT_API_ERROR: str = "usage_limit_reached"

RATE_LIMIT_ERROR: str = "rate_limit"

QUOTA_REJECTED: str = "rejected"

LIMIT_TEXT = re.compile(
    r"(You['’]ve hit your (?:session|weekly|daily|opus|sonnet|usage)?\s*limit"
    r"|Claude(?: AI)? usage limit reached)",
    re.IGNORECASE,
)

KIND_SESSION: str = "session"
KIND_WEEKLY: str = "weekly"
KIND_WEEKLY_MODEL: str = "weekly_model"
KIND_OTHER: str = "other"

_KIND_BY_RATE_LIMIT_TYPE: Dict[str, str] = {
    "five_hour": KIND_SESSION,
    "seven_day": KIND_WEEKLY,
    "seven_day_opus": KIND_WEEKLY_MODEL,
    "seven_day_sonnet": KIND_WEEKLY_MODEL,
}


@dataclass(frozen=True)
class UsageLimit:

    kind: str
    resets_at: Optional[datetime]
    message: str
    since: Optional[datetime]


@dataclass(frozen=True)
class LimitStop:

    uuid: Optional[str]
    timestamp: Optional[datetime]
    resets_at: Optional[datetime]
    rate_limit_type: Optional[str]

    @property
    def kind(self) -> str:
        return _KIND_BY_RATE_LIMIT_TYPE.get(str(self.rate_limit_type), KIND_OTHER)


def is_limit_text(text: Optional[str]) -> bool:
    return bool(text) and LIMIT_TEXT.search(text) is not None


def record_text(record: Dict[str, Any]) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        block["text"] for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    )


def is_limit_stop(record: Any) -> bool:
    if (
        not isinstance(record, dict)
        or record.get("type") != "assistant"
        or record.get("isSidechain") is True
        or record.get("isApiErrorMessage") is not True
        or record.get("apiErrorIsTransient") is True
    ):
        return False
    quota = record.get("quotaLimits")
    if isinstance(quota, dict):
        return quota.get("status") == QUOTA_REJECTED
    if record.get("apiError") == USAGE_LIMIT_API_ERROR:
        return True
    text = record_text(record)
    return is_limit_text(text) and (
        record.get("error") == RATE_LIMIT_ERROR or "usage limit reached" in text.lower()
    )


def parse_limit_stop(record: Any) -> Optional[LimitStop]:
    if not is_limit_stop(record):
        return None
    info = _limit_info(record)
    uuid = record.get("uuid")
    return LimitStop(
        uuid=uuid if isinstance(uuid, str) and uuid else None,
        timestamp=parse_timestamp(record.get("timestamp")),
        resets_at=_resets_at(info),
        rate_limit_type=str(info["rateLimitType"]) if info.get("rateLimitType") else None,
    )


def _resets_at(info: Dict[str, Any]) -> Optional[datetime]:
    epoch = info.get("resetsAt")
    if isinstance(epoch, (int, float)) and not isinstance(epoch, bool) and epoch > 0:
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _limit_info(record: Dict[str, Any]) -> Dict[str, Any]:
    params = record.get("apiErrorParams")
    info = params.get("rate_limit_info") if isinstance(params, dict) else None
    if not isinstance(info, dict):
        info = record.get("quotaLimits")
    return info if isinstance(info, dict) else {}


def usage_limit_from_record(record: Any) -> Optional[UsageLimit]:
    stop = parse_limit_stop(record)
    if stop is None:
        return None
    message = ""
    body = record.get("message")
    content = body.get("content") if isinstance(body, dict) else None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                lines = block["text"].strip().splitlines()
                message = lines[0].strip() if lines else ""
                break
    return UsageLimit(stop.kind, stop.resets_at, message, stop.timestamp)


def active_usage_limit(limit: Optional[UsageLimit], now: datetime) -> Optional[UsageLimit]:
    if limit is None or (limit.resets_at is not None and limit.resets_at <= now):
        return None
    return limit
