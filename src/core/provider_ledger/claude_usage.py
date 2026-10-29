
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import httpx
import structlog

from src.core.provider_ledger.payload_fields import (
    parse_reset_at,
    parse_retry_after_seconds,
    read_percent,
)
from src.models.provider_ledger import FetchOutcome, UsageWindow

logger = structlog.get_logger()

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

OAUTH_BETA = "oauth-2025-04-20"

USER_AGENT = "claude-cli/2.1.198 (external, cli)"

_WINDOWS: Tuple[Tuple[str, str, int], ...] = (
    ("five_hour", "5h", 18000),
    ("seven_day", "7d", 604800),
    ("seven_day_opus", "7d opus", 604800),
    ("seven_day_sonnet", "7d sonnet", 604800),
)

PROFILE_SCOPE = "user:profile"


def build_request(access_token: str) -> Tuple[str, Dict[str, str]]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "anthropic-beta": OAUTH_BETA,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    return USAGE_URL, headers


def parse_usage(payload: dict) -> List[UsageWindow]:
    windows: List[UsageWindow] = []
    for kind, label, seconds in _WINDOWS:
        raw = payload.get(kind)
        if not isinstance(raw, dict):
            continue
        used = read_percent(raw.get("utilization"))
        if used is None:
            continue
        windows.append(
            UsageWindow(
                kind=kind,
                label=label,
                used_pct=used,
                window_seconds=seconds,
                resets_at=parse_reset_at(raw.get("resets_at")),
            )
        )
    return windows


async def fetch_usage(client: httpx.AsyncClient, access_token: str) -> FetchOutcome:
    url, headers = build_request(access_token)
    try:
        response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        logger.warning("provider_ledger_claude_timeout", error=type(exc).__name__)
        return FetchOutcome(state="error", error="timeout")
    except httpx.RequestError as exc:
        logger.warning("provider_ledger_claude_unreachable", error=type(exc).__name__)
        return FetchOutcome(state="error", error="unreachable")

    status = response.status_code
    if status == 200:
        return _read_body(response)
    if status == 401:
        logger.info("provider_ledger_claude_expired", status=status)
        return FetchOutcome(state="expired", error="unauthorized")
    if status == 403:
        return _read_refusal(response)
    if status == 429:
        seconds = parse_retry_after_seconds(response.headers.get("Retry-After"))
        logger.warning(
            "provider_ledger_claude_rate_limited",
            status=status,
            retry_after_seconds=seconds,
        )
        return FetchOutcome(
            state="rate_limited", retry_after_seconds=seconds, error="rate_limited"
        )
    logger.warning("provider_ledger_claude_http_error", status=status)
    return FetchOutcome(state="error", error=f"http_{status}")


def _read_body(response: httpx.Response) -> FetchOutcome:
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        logger.warning("provider_ledger_claude_invalid_json", status=200)
        return FetchOutcome(state="error", error="invalid_json")
    if not isinstance(payload, dict):
        logger.warning("provider_ledger_claude_unexpected_payload", status=200)
        return FetchOutcome(state="error", error="unexpected_payload")
    return FetchOutcome(state="ok", windows=parse_usage(payload))


def _read_refusal(response: httpx.Response) -> FetchOutcome:
    names_scope = False
    try:
        names_scope = PROFILE_SCOPE in response.text
    except (ValueError, UnicodeDecodeError):
        names_scope = False
    error = f"missing scope {PROFILE_SCOPE}" if names_scope else "forbidden"
    logger.warning(
        "provider_ledger_claude_refused", status=403, missing_scope=names_scope
    )
    return FetchOutcome(state="refused", error=error)
