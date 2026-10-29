
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
import structlog

from src.core.provider_ledger.payload_fields import (
    parse_reset_at,
    parse_retry_after_seconds,
    read_percent,
)
from src.models.provider_ledger import FetchOutcome, UsageWindow

logger = structlog.get_logger()

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

USER_AGENT = "codex_cli_rs/0.76.0 (macos) cloude-code"

AUTH_CLAIM = "https://api.openai.com/auth"

_WINDOWS: Tuple[Tuple[str, str], ...] = (
    ("primary", "primary_window"),
    ("secondary", "secondary_window"),
)

_MINUTES_PER_DAY = 1440


def account_id_from_id_token(id_token: str) -> Optional[str]:
    return _auth_claim_string(id_token, "chatgpt_account_id")


def user_id_from_id_token(id_token: str) -> Optional[str]:
    return _auth_claim_string(id_token, "chatgpt_user_id")


def plan_type_from_id_token(id_token: str) -> Optional[str]:
    return _auth_claim_string(id_token, "chatgpt_plan_type")


def build_request(
    access_token: str, account_id: Optional[str]
) -> Tuple[str, Dict[str, str]]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    return USAGE_URL, headers


def parse_usage(payload: dict) -> List[UsageWindow]:
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return []

    windows: List[UsageWindow] = []
    for kind, key in _WINDOWS:
        raw = rate_limit.get(key)
        if not isinstance(raw, dict):
            continue
        used = read_percent(raw.get("used_percent"))
        if used is None:
            continue
        seconds = _window_seconds(raw)
        windows.append(
            UsageWindow(
                kind=kind,
                label=_label(seconds, kind),
                used_pct=used,
                window_seconds=seconds,
                resets_at=parse_reset_at(raw.get("reset_at")),
            )
        )
    return windows


async def fetch_usage(
    client: httpx.AsyncClient, access_token: str, account_id: Optional[str]
) -> FetchOutcome:
    url, headers = build_request(access_token, account_id)
    try:
        response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        logger.warning("provider_ledger_codex_timeout", error=type(exc).__name__)
        return FetchOutcome(state="error", error="timeout")
    except httpx.RequestError as exc:
        logger.warning("provider_ledger_codex_unreachable", error=type(exc).__name__)
        return FetchOutcome(state="error", error="unreachable")

    status = response.status_code
    if status == 200:
        return _read_body(response)
    if status == 401:
        logger.info("provider_ledger_codex_expired", status=status)
        return FetchOutcome(state="expired", error="unauthorized")
    if status == 403:
        logger.warning("provider_ledger_codex_refused", status=status)
        return FetchOutcome(state="refused", error="forbidden")
    if status == 429:
        seconds = parse_retry_after_seconds(response.headers.get("Retry-After"))
        logger.warning(
            "provider_ledger_codex_rate_limited",
            status=status,
            retry_after_seconds=seconds,
        )
        return FetchOutcome(
            state="rate_limited", retry_after_seconds=seconds, error="rate_limited"
        )
    logger.warning("provider_ledger_codex_http_error", status=status)
    return FetchOutcome(state="error", error=f"http_{status}")


def _read_body(response: httpx.Response) -> FetchOutcome:
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        logger.warning("provider_ledger_codex_invalid_json", status=200)
        return FetchOutcome(state="error", error="invalid_json")
    if not isinstance(payload, dict):
        logger.warning("provider_ledger_codex_unexpected_payload", status=200)
        return FetchOutcome(state="error", error="unexpected_payload")

    plan = payload.get("plan_type")
    return FetchOutcome(
        state="ok",
        windows=parse_usage(payload),
        plan=plan if isinstance(plan, str) and plan else None,
    )


def _auth_claim_string(id_token: str, field: str) -> Optional[str]:
    claims = _decode_claims(id_token)
    if claims is None:
        return None
    block = claims.get(AUTH_CLAIM)
    if not isinstance(block, dict):
        return None
    value = block.get(field)
    if not isinstance(value, str) or not value:
        return None
    return value


def _decode_claims(id_token: str) -> Optional[Dict[str, Any]]:
    if not isinstance(id_token, str):
        return None
    parts = id_token.split(".")
    if len(parts) != 3:
        return None
    segment = parts[1]
    padding = "=" * (-len(segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(segment + padding)
    except (binascii.Error, ValueError):
        return None
    try:
        claims = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    return claims


def _window_seconds(window: Dict[str, Any]) -> Optional[int]:
    seconds = window.get("limit_window_seconds")
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
        return seconds
    minutes = window.get("window_minutes")
    if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
        return minutes * 60
    return None


def _label(seconds: Optional[int], kind: str) -> str:
    if seconds is None or seconds < 60:
        return kind
    minutes = seconds // 60
    if minutes % _MINUTES_PER_DAY == 0:
        return f"{minutes // _MINUTES_PER_DAY}d"
    if minutes < _MINUTES_PER_DAY and minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"
