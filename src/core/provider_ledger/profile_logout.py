
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.config.provider_accounts import ProviderAccount
from src.core.provider_ledger import refresh_poke
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS, login_profile_dir

logger = structlog.get_logger()

__all__ = [
    "LOGOUT_ARGS",
    "LOGOUT_FAILED",
    "LOGOUT_OK",
    "LOGOUT_SKIPPED",
    "build_logout",
    "log_out_profile",
]

LOGOUT_OK = "ok"
LOGOUT_SKIPPED = "skipped"
LOGOUT_FAILED = "failed"

LOGOUT_BINARY_MISSING = "logout_binary_missing"
LOGOUT_SPAWN_FAILED = "logout_spawn_failed"
LOGOUT_TIMED_OUT = "logout_timed_out"
LOGOUT_EXIT_NONZERO = "logout_exit_nonzero"

LOGOUT_ARGS: Dict[str, Tuple[str, ...]] = {
    "claude": ("auth", "logout"),
    "codex": ("logout",),
}


def _codex_command(
    profile_dir: str, binary: str, *args: str
) -> Tuple[List[str], Dict[str, str]]:
    env = dict(os.environ)
    for name in refresh_poke.SUPPRESSING_ENV_VARS:
        env.pop(name, None)
    env[PROFILE_ENV_VARS["codex"]] = profile_dir
    return [binary, *args], env


def build_logout(
    account: ProviderAccount, binary: str
) -> Tuple[List[str], Dict[str, str]]:
    profile_dir = login_profile_dir(account)
    args = LOGOUT_ARGS[account.provider]
    if account.provider == "claude":
        argv, env = refresh_poke.build_claude_command(profile_dir, binary, *args)
    else:
        argv, env = _codex_command(profile_dir, binary, *args)
    for provider, variable in PROFILE_ENV_VARS.items():
        if provider != account.provider:
            env.pop(variable, None)
    return argv, env


def _failure_reason(outcome: Any) -> str:
    if outcome.timed_out:
        return LOGOUT_TIMED_OUT
    if not outcome.ran:
        return LOGOUT_SPAWN_FAILED
    return LOGOUT_EXIT_NONZERO


async def log_out_profile(
    account: ProviderAccount,
    *,
    run: Optional[Callable[..., Awaitable[Any]]] = None,
    resolve: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    runner = run if run is not None else refresh_poke.run_poke
    resolver = resolve if resolve is not None else refresh_poke.resolve_binary
    if not account.managed:
        logger.info("provider_logout_skipped_unmanaged", account_id=account.id)
        return LOGOUT_SKIPPED
    if account.provider not in LOGOUT_ARGS:
        logger.info(
            "provider_logout_skipped_no_command",
            account_id=account.id,
            provider=account.provider,
        )
        return LOGOUT_SKIPPED

    binary = resolver(account.provider)
    if binary is None:
        logger.warning(
            "provider_logout_failed",
            account_id=account.id,
            provider=account.provider,
            reason=LOGOUT_BINARY_MISSING,
        )
        return LOGOUT_FAILED

    argv, env = build_logout(account, binary)
    outcome = await runner(argv, env, timeout=refresh_poke.COMMAND_TIMEOUT_SECONDS)
    if outcome.ran and not outcome.timed_out and outcome.exit_code == 0:
        logger.info(
            "provider_logout_ran", account_id=account.id, provider=account.provider
        )
        return LOGOUT_OK
    logger.warning(
        "provider_logout_failed",
        account_id=account.id,
        provider=account.provider,
        reason=_failure_reason(outcome),
    )
    return LOGOUT_FAILED
