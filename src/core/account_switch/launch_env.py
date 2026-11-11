
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.account_switch import profile_setup, shared_links, store
from src.core.account_switch.active import PROVIDERS, find_account
from src.core.provider_ledger import accounts_store, poller_scan, relay_accounts
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS, login_profile_dir

if TYPE_CHECKING:
    from src.core.account_switch.codex_follow import KeptHome

logger = structlog.get_logger()

AccountEnv = Dict[str, Optional[str]]


def profile_env_for(account: ProviderAccount) -> AccountEnv:
    provider = account.provider
    if provider not in PROVIDERS:
        return {}
    if provider == "codex":
        return _codex_launch_env(account)
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
    if not report.resume_safe and not relay_accounts.is_relay_account(account):
        logger.warning(
            "account_switch_profile_not_shared",
            provider=provider,
            account_id=account.id,
            required=report.entries.get(shared_links.REQUIRED_ENTRY[provider]),
        )
        return {}
    return {variable: login_profile_dir(account)}


def _codex_launch_env(account: ProviderAccount) -> AccountEnv:
    from src.core.pack.relay.codex_target import codex_relay_env

    home = login_profile_dir(account)
    if not Path(home).is_dir():
        logger.warning("account_switch_codex_home_missing", account_id=account.id)
        return {}
    if relay_accounts.is_codex_relay_account(account):
        return dict(codex_relay_env(home))
    return {"CODEX_HOME": home}


def _codex_follow_env(config_path: Path, accounts: List[ProviderAccount]) -> AccountEnv:
    from src.core.account_switch import codex_follow

    try:
        account_id = codex_follow.follow_active_account(config_path)
    except codex_follow.CodexAccountRefused:
        return {}
    account = find_account(relay_accounts.with_relay(accounts), account_id, "codex")
    return profile_env_for(account) if account is not None else {}


def codex_removals() -> AccountEnv:
    return _removals("codex")


def _removals(provider: str) -> AccountEnv:
    from src.core.pack.relay.codex_target import codex_relay_env

    if provider == "codex":
        return dict.fromkeys(codex_relay_env(""))
    return {PROFILE_ENV_VARS[provider]: None}


def account_env(
    config_path: Path,
    *,
    read_switch: Callable[[Path], ProviderAccountSwitchConfig] = store.read_switch,
    list_accounts: Callable[[Path], List[ProviderAccount]] = accounts_store.list_accounts,
    claude_account: Optional[str] = None,
    family: str = "claude",
) -> AccountEnv:
    try:
        switch = read_switch(config_path)
        accounts = list_accounts(config_path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("account_switch_env_unavailable", error=type(exc).__name__)
        return {}
    env: AccountEnv = {}
    providers = (family,) if family in PROVIDERS else ("claude",)
    if claude_account is not None:
        chosen = find_account(poller_scan.with_auto_default(accounts), claude_account, providers[0])
        if chosen is not None:
            try:
                return dict(profile_env_for(chosen))
            except (OSError, ValueError) as exc:
                logger.warning("account_switch_env_failed", provider=providers[0],
                               account_id=chosen.id, error=type(exc).__name__)
                return {}
        logger.info("account_switch_session_account_gone", account_id=claude_account)
    for provider in providers:
        pointer = switch.active_for(provider)
        if pointer is None:
            if provider == "codex":
                env.update(_codex_follow_env(config_path, accounts) or {})
            continue
        account = find_account(relay_accounts.with_relay(accounts), pointer, provider)
        if account is None:
            if provider == "codex":
                followed = _codex_follow_env(config_path, accounts)
                if followed:
                    env.update(followed)
                    continue
            logger.info("account_switch_pointer_stale", provider=provider, account_id=pointer)
            env.update(_removals(provider))
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
    merged.setdefault(PROFILE_ENV_VARS["claude"], None)
    return merged


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


async def new_pane_env(
    spawn_env: Mapping[str, str], *, claude_account: Optional[str] = None, family: str = "claude"
) -> Dict[str, Optional[str]]:
    env = await asyncio.to_thread(account_env, _config_path(), claude_account=claude_account, family=family)
    return apply_to_new_pane(spawn_env, env)


async def _kept_pane_home(
    config_path: Path, pane: Optional[Tuple[str, str]], claude_account: Optional[str], family: str, read_profile=None,
) -> Optional["KeptHome"]:
    from src.core.account_switch import codex_follow, pane_account

    if family != "codex" or claude_account is not None or pane is None:
        return None
    reader = read_profile or pane_account.read_pane_profile
    current = await reader(pane[0], pane[1], PROFILE_ENV_VARS["codex"])
    if not current.readable:
        return None
    try:
        return await asyncio.to_thread(codex_follow.kept_home, config_path, current.value)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("account_switch_codex_keep_unavailable", error=type(exc).__name__)
        return None


async def respawn_pane_env(
    spawn_env: Mapping[str, str], *, claude_account: Optional[str] = None, family: str = "claude",
    pane: Optional[Tuple[str, str]] = None, read_profile=None,
) -> Dict[str, Optional[str]]:
    path = _config_path()
    kept = await _kept_pane_home(path, pane, claude_account, family, read_profile)
    if kept is not None and kept.account_id is None:
        env: AccountEnv = {}
    else:
        account = kept.account_id if kept is not None else claude_account
        env = await asyncio.to_thread(account_env, path, claude_account=account, family=family)
    merged = apply_to_new_pane(spawn_env, env)
    if family == "codex":
        for variable in _removals("codex"):
            merged.setdefault(variable, None)
    return merged


UNUSABLE_DETAIL = "account profile not usable, pane unchanged"

CODEX_FOLLOW_DETAIL = {
    "no_codex_account": "no codex account is logged in, so the pane would start on a sign-in screen; log one in under providers, pane unchanged",
    "codex_account_choice": "more than one codex account is logged in; restart with the account you want, pane unchanged",
}


def _codex_follow_refusal(config_path: Path, claude_account: Optional[str], family: str) -> Optional[str]:
    from src.core.account_switch import codex_follow

    if family != "codex" or claude_account is not None:
        return None
    try:
        codex_follow.follow_active_account(config_path)
    except codex_follow.CodexAccountRefused as exc:
        logger.warning("account_switch_codex_follow_refused", code=exc.code)
        return CODEX_FOLLOW_DETAIL[exc.code]
    except (FileNotFoundError, ValueError, OSError):
        return None
    return None


def _unusable_targets(
    config_path: Path, claude_account: Optional[str] = None, family: str = "claude"
) -> List[ProviderAccount]:
    try:
        switch = store.read_switch(config_path)
        accounts = accounts_store.list_accounts(config_path)
    except (FileNotFoundError, ValueError, OSError):
        return []
    bad: List[ProviderAccount] = []
    providers = (family,) if family in PROVIDERS else ("claude",)
    if claude_account is not None:
        chosen = find_account(poller_scan.with_auto_default(accounts), claude_account, providers[0])
        if chosen is not None:
            return [] if profile_env_for(chosen) else [chosen]
    for provider in providers:
        pointer = switch.active_for(provider)
        account = find_account(relay_accounts.with_relay(accounts), pointer, provider) if pointer is not None else None
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
    family: str = "claude",
) -> Optional[str]:
    from src.core.account_switch import pane_account

    reader = read_profile or pane_account.read_pane_profile
    path = config_path if config_path is not None else _config_path()
    if await _kept_pane_home(path, (socket, tmux_name), claude_account, family, reader) is not None:
        return None
    follow = await asyncio.to_thread(_codex_follow_refusal, path, claude_account, family)
    if follow:
        return follow
    bad = await asyncio.to_thread(_unusable_targets, path, claude_account, family)
    for account in bad:
        current = await reader(socket, tmux_name, PROFILE_ENV_VARS[account.provider])
        if not current.readable or current.value != login_profile_dir(account):
            logger.warning("account_switch_restart_refused", account_id=account.id, tmux_session=tmux_name)
            return UNUSABLE_DETAIL
    return None
