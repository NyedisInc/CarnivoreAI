
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def epoch_millis_to_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def epoch_seconds_to_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def jwt_claims(token: Any) -> Dict[str, Any]:
    if not isinstance(token, str):
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}
