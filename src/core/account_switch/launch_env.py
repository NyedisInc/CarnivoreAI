
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

import structlog

from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.account_switch import profile_setup, shared_links, store
from src.core.account_switch.active import PROVIDERS, find_account
from src.core.provider_ledger import accounts_store, poller_scan
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS, login_profile_dir

logger = structlog.get_logger()

AccountEnv = Dict[str, Optional[str]]


def profile_env_for(account: ProviderAccount) -> AccountEnv:
    provider = account.provider
    if provider not in PROVIDERS:
        return {}
    variable = PROFILE_ENV_VARS[provider]
    profile = profile_dir_for(account)
    if shared_links.is_default_profile(provider, profile):
        return {variable: None}
    if not account.managed:
        logger.warning("account_switch_profile_not_managed", account_id=account.id)
        return {}
    if not profile_setup.setup_done(account):
        logger.warning("account_switch_profile_needs_setup", provider=provider, account_id=account.id)
        return {}
    report = shared_links.ensure_shared_links(profile, provider, managed=account.managed)
    if not report.resume_safe:
        logger.warning(
            "account_switch_profile_not_shared",
            provider=provider,
            account_id=account.id,
            required=report.entries.get(shared_links.REQUIRED_ENTRY[provider]),
        )
        return {}
    return {variable: login_profile_dir(account)}


def account_env(
    config_path: Path,
    *,
    read_switch: Callable[[Path], ProviderAccountSwitchConfig] = store.read_switch,
    list_accounts: Callable[[Path], List[ProviderAccount]] = accounts_store.list_accounts,
    claude_account: Optional[str] = None,
) -> AccountEnv:
    try:
        switch = read_switch(config_path)
        accounts = list_accounts(config_path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("account_switch_env_unavailable", error=type(exc).__name__)
        return {}
    env: AccountEnv = {}
    if claude_account is not None:
        chosen = find_account(poller_scan.with_auto_default(accounts), claude_account, "claude")
        if chosen is not None:
            try:
                return dict(profile_env_for(chosen))
            except (OSError, ValueError) as exc:
                logger.warning("account_switch_env_failed", provider="claude",
                               account_id=chosen.id, error=type(exc).__name__)
                return {}
        logger.info("account_switch_session_account_gone", account_id=claude_account)
    for provider in PROVIDERS:
        pointer = switch.active_for(provider)
        if pointer is None:
            continue
        account = find_account(accounts, pointer, provider)
        if account is None:
            logger.info("account_switch_pointer_stale", provider=provider, account_id=pointer)
            env[PROFILE_ENV_VARS[provider]] = None
            continue
        try:
            env.update(profile_env_for(account))
        except (OSError, ValueError) as exc:
            logger.warning(
                "account_switch_env_failed",
                provider=provider,
                account_id=account.id,
                error=type(exc).__name__,
            )
    return env


def apply_to_new_pane(
    spawn_env: Mapping[str, str], env: AccountEnv
) -> Dict[str, Optional[str]]:
    merged: Dict[str, Optional[str]] = dict(spawn_env)
    merged.update(env)
    for provider in PROVIDERS:
        merged.setdefault(PROFILE_ENV_VARS[provider], None)
    return merged


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


async def new_pane_env(
    spawn_env: Mapping[str, str], *, claude_account: Optional[str] = None
) -> Dict[str, Optional[str]]:
    env = await asyncio.to_thread(account_env, _config_path(), claude_account=claude_account)
    return apply_to_new_pane(spawn_env, env)


async def respawn_pane_env(
    spawn_env: Mapping[str, str], *, claude_account: Optional[str] = None
) -> Dict[str, Optional[str]]:
    env = await asyncio.to_thread(account_env, _config_path(), claude_account=claude_account)
    return apply_to_new_pane(spawn_env, env)


UNUSABLE_DETAIL = "account profile not usable, pane unchanged"


def _unusable_targets(
    config_path: Path, claude_account: Optional[str] = None
) -> List[ProviderAccount]:
    try:
        switch = store.read_switch(config_path)
        accounts = accounts_store.list_accounts(config_path)
    except (FileNotFoundError, ValueError, OSError):
        return []
    bad: List[ProviderAccount] = []
    if claude_account is not None:
        chosen = find_account(poller_scan.with_auto_default(accounts), claude_account, "claude")
        if chosen is not None:
            return [] if profile_env_for(chosen) else [chosen]
    for provider in PROVIDERS:
        pointer = switch.active_for(provider)
        account = find_account(accounts, pointer, provider) if pointer is not None else None
        if account is not None and not profile_env_for(account):
            bad.append(account)
    return bad


async def restart_refusal(
    socket: str,
    tmux_name: str,
    *,
    config_path: Optional[Path] = None,
    read_profile=None,
    claude_account: Optional[str] = None,
) -> Optional[str]:
    """Why a restart must NOT go ahead, or None when it may.

    Description: a restart is how a pane moves to the active account. When
      the active account's profile is unusable ``account_env`` omits the
      variable, so the pane would relaunch unchanged and report success.
      This refuses instead, unless the pane already runs on that profile.
    Inputs: socket (str); tmux_name (str); config_path, read_profile -
      injectable (default config.json and ``pane_account.read_pane_profile``).
      claude_account (str | None) - the session's own account, which is the
      target instead of the global pointer.
    Output: str | None - ``UNUSABLE_DETAIL`` or None.
    Example: await restart_refusal('cloude', 'cloude_x')
    """
    from src.core.account_switch import pane_account

    reader = read_profile or pane_account.read_pane_profile
    path = config_path if config_path is not None else _config_path()
    bad = await asyncio.to_thread(_unusable_targets, path, claude_account)
    for account in bad:
        current = await reader(socket, tmux_name, PROFILE_ENV_VARS[account.provider])
        if not current.readable or current.value != login_profile_dir(account):
            logger.warning("account_switch_restart_refused", account_id=account.id, tmux_session=tmux_name)
            return UNUSABLE_DETAIL
    return None
