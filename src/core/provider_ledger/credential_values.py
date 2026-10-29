"""Coercing the scalars a credential store holds, without ever raising.

The credential readers parse documents two other programs wrote and a
human may have hand-edited, so every scalar arrives as "whatever was
there". These helpers turn one of those into a typed value or into
``None``, and ``None`` always means COULD NOT BE DETERMINED.

**NONE IS NEVER ZERO AND NEVER NOW.** An expiry this app could not read
is not an expiry that has passed, and a fabricated one would report a
live account as logged out. So every helper here fails to ``None`` and
the ladder above it decides what an absent value means.

**THE TWO EPOCH UNITS ARE SEPARATE FUNCTIONS ON PURPOSE.** Claude Code
writes ``expiresAt`` in MILLISECONDS and a JWT ``exp`` claim is in
SECONDS. One function taking a unit argument is one call site away from
putting every Claude expiry in 1970 and reporting every account expired,
which is a failure that looks like a real finding.
"""

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
    """Decode a JWT's claims WITHOUT verifying its signature.

    Description: decode only, which is exactly what Codex's own client
      does with this token, and the only thing this app could do since it
      holds no signing key. A token that will not decode answers with NO
      CLAIMS rather than raising, because a token this app cannot read is
      one it knows nothing from.

      Sibling readers exist for two specific claims in
      :mod:`src.core.provider_ledger.codex_usage`
      (``account_id_from_id_token`` and ``plan_type_from_id_token``);
      this is the general decode the other claims are read through.
    Inputs: token (Any) - the JWT, or anything at all.
    Output: dict - the claim set, empty when it could not be read.
    Example: jwt_claims("not a jwt")  # {}
    """
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
