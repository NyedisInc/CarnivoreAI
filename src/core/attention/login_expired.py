
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from src.core.attention.usage_limit import record_text
from src.core.session_status_seed_records import parse_timestamp

AUTH_FAILED_ERROR: str = "authentication_failed"


@dataclass(frozen=True)
class LoginExpired:

    message: str
    since: Optional[datetime]


def is_login_expired(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and record.get("type") == "assistant"
        and record.get("isSidechain") is not True
        and record.get("isApiErrorMessage") is True
        and record.get("error") == AUTH_FAILED_ERROR
    )


def login_expired_from_record(record: Any) -> Optional[LoginExpired]:
    if not is_login_expired(record):
        return None
    lines = record_text(record).strip().splitlines()
    return LoginExpired(lines[0].strip() if lines else "", parse_timestamp(record.get("timestamp")))
