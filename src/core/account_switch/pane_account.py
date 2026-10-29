
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.account_switch.active import ActiveAccount
from src.core.hosts.identity import is_remote_info
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
from src.core.session_token_usage.account_resolve import accounts_for_default_login
from src.core.tmux_discovery import tmux_argv_prefix

logger = structlog.get_logger()

FAMILY_PROVIDER = {"claude": "claude", "codex": "codex"}

READ_CONCURRENCY = 8

READ_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class PaneProfile:
    """What one pane's profile variable says.

    Fields:
        readable: False when tmux could not answer.
        value: the directory the pane was given, or None when it runs on
            the provider's default (the variable is removed or unset).
        inherited: the SESSION never set the variable, so the pane has the
            tmux server's global value for it (resolved by the reader).
    """

    readable: bool
    value: Optional[str] = None
    inherited: bool = False


UNREADABLE = PaneProfile(readable=False)


def parse_show_environment(stdout: bytes, returncode: int, variable: str) -> PaneProfile:
    text = stdout.decode("utf-8", errors="replace").strip()
    if returncode == 0 and text.startswith(f"{variable}="):
        return PaneProfile(readable=True, value=text[len(variable) + 1 :])
    if returncode == 0 and text == f"-{variable}":
        return PaneProfile(readable=True, value=None)
    if returncode == 1:
        return PaneProfile(readable=True, value=None, inherited=True)
    return UNREADABLE


async def read_pane_profile(socket: str, tmux_name: str, variable: str) -> PaneProfile:
    argv = tmux_argv_prefix(socket) + ["show-environment", "-t", f"={tmux_name}", variable]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        logger.debug("account_switch_pane_read_failed", error=type(exc).__name__)
        return UNREADABLE
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), READ_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.debug("account_switch_pane_read_failed", error="TimeoutError")
        return UNREADABLE
    if proc.returncode == 1 and b"unknown variable" not in stderr:
        return UNREADABLE
    profile = parse_show_environment(stdout, proc.returncode or 0, variable)
    if not profile.inherited:
        return profile
    return await _read_global(socket, variable)


async def _read_global(socket: str, variable: str) -> PaneProfile:
    argv = tmux_argv_prefix(socket) + ["show-environment", "-g", variable]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return UNREADABLE
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), READ_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return UNREADABLE
    if proc.returncode == 1 and b"unknown variable" in stderr:
        return PaneProfile(readable=True, value=None)
    profile = parse_show_environment(stdout, proc.returncode or 0, variable)
    return PaneProfile(readable=True, value=profile.value) if profile.readable else UNREADABLE


def _canonical(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def account_for_profile(
    accounts: List[ProviderAccount], provider: str, profile: PaneProfile
) -> Optional[str]:
    if not profile.readable:
        return None
    if profile.value is None:
        matched = accounts_for_default_login(accounts, provider=provider)
    else:
        wanted = _canonical(profile.value)
        matched = [
            a for a in accounts
            if a.provider == provider and _canonical(profile_dir_for(a)) == wanted
        ]
    return matched[0].id if len(matched) == 1 else None


async def resolve_pane_account(
    socket: str,
    tmux_name: str,
    provider: str,
    accounts: List[ProviderAccount],
    *,
    gate: Optional[asyncio.Semaphore] = None,
) -> Optional[str]:
    variable = PROFILE_ENV_VARS[provider]
    if gate is None:
        profile = await read_pane_profile(socket, tmux_name, variable)
    else:
        async with gate:
            profile = await read_pane_profile(socket, tmux_name, variable)
    return await asyncio.to_thread(account_for_profile, accounts, provider, profile)


async def running_elsewhere(
    infos: List[Any],
    *,
    socket: str,
    accounts: List[ProviderAccount],
    active: Dict[str, ActiveAccount],
) -> List[Dict[str, Any]]:
    """Every running agent session whose account is not its provider's active one.

    Description: reads the pane's own profile variable (bounded, off
      nothing that blocks). A session is listed only when its account is
      KNOWN and differs from a KNOWN active account: an unreadable pane,
      an unmatched directory or a provider with no active account is not
      offered a restart, because "elsewhere" would then be a guess.
      GOTCHA 1: family, name, label and status are on the WRAPPER; the id
      is on the nested ``.session``.
    Inputs: infos (list[SessionInfo]); socket (str); accounts; active
      (provider -> ActiveAccount).
    Output: list[dict] - ``session_id``, ``tmux_session``, ``label``,
      ``status``, ``provider``, ``account_id``, ``active_account_id``.
    Example: await running_elsewhere(infos, socket='cloude', accounts=rows,
      active={'claude': a})
    """
    gate = asyncio.Semaphore(READ_CONCURRENCY)

    async def one(info: Any) -> Optional[Dict[str, Any]]:
        provider = FAMILY_PROVIDER.get(info.agent_family or "")
        name = info.tmux_session
        chosen = active.get(provider) if provider else None
        if provider is None or not name or chosen is None or chosen.account_id is None:
            return None
        if is_remote_info(info):
            return None
        if info.activity_status == "dead":
            return None
        account_id = await resolve_pane_account(
            socket, name, provider, accounts, gate=gate
        )
        if account_id is None or account_id == chosen.account_id:
            return None
        return {
            "session_id": info.session.id,
            "tmux_session": name,
            "label": info.label,
            "status": info.activity_status,
            "provider": provider,
            "account_id": account_id,
            "active_account_id": chosen.account_id,
        }

    rows = await asyncio.gather(*(one(info) for info in infos))
    return [row for row in rows if row is not None]


async def sessions_on_account(
    infos: List[Any],
    *,
    socket: str,
    accounts: List[ProviderAccount],
    account_id: str,
) -> List[str]:
    target = next((a for a in accounts if a.id == account_id), None)
    if target is None or target.provider not in PROFILE_ENV_VARS:
        return []
    wanted = _canonical(profile_dir_for(target))
    gate = asyncio.Semaphore(READ_CONCURRENCY)

    async def one(info: Any) -> Optional[str]:
        provider = FAMILY_PROVIDER.get(info.agent_family or "")
        name = info.tmux_session
        if provider != target.provider or not name or info.activity_status == "dead":
            return None
        if is_remote_info(info):
            return None
        async with gate:
            profile = await read_pane_profile(socket, name, PROFILE_ENV_VARS[provider])
        if not profile.readable:
            return name
        return name if profile.value and _canonical(profile.value) == wanted else None

    names = await asyncio.gather(*(one(info) for info in infos))
    return [name for name in names if name is not None]
