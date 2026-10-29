
from __future__ import annotations

import asyncio
from typing import Any, Iterable, Optional

import structlog

from src.config.provider_accounts import ProviderAccount
from src.core.provider_ledger.login_command import (
    login_command_for,
    login_profile_dir,
)

logger = structlog.get_logger()

__all__ = ["find_account", "type_login_command"]


def find_account(
    accounts: Iterable[ProviderAccount], account_id: str
) -> Optional[ProviderAccount]:
    for account in accounts:
        if account.id == account_id:
            return account
    return None


async def type_login_command(
    *,
    session_id: str,
    account: ProviderAccount,
    backend: Any,
    attempts: int,
    delay_seconds: float,
    device_auth: bool = False,
) -> str:
    profile_dir = login_profile_dir(account)
    try:
        text = login_command_for(account, profile_dir, device_auth)
    except ValueError as exc:
        logger.warning(
            "provider_login_command_unavailable",
            session_id=session_id,
            account_id=account.id,
            provider=account.provider,
            error=str(exc),
        )
        return "failed"

    payload = (text + "\n").encode("utf-8")
    last_error: Optional[str] = None
    for attempt in range(attempts):
        try:
            await backend.write(payload)
            logger.info(
                "provider_login_typed",
                session_id=session_id,
                account_id=account.id,
                provider=account.provider,
                attempt=attempt,
            )
            return "issued"
        except (OSError, RuntimeError, ValueError) as exc:
            last_error = str(exc)
            await asyncio.sleep(delay_seconds)

    logger.warning(
        "provider_login_type_failed",
        session_id=session_id,
        account_id=account.id,
        provider=account.provider,
        error=last_error,
        attempts=attempts,
    )
    return "failed"
