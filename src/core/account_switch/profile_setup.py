
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import structlog

from src.config.provider_accounts import (
    DEFAULT_CLAUDE_CONFIG_DIR,
    ProviderAccount,
    profile_dir_for,
)
from src.core import config_writer
from src.core.account_switch import shared_mcp
from src.core.provider_ledger import accounts_store, refresh_guard
from src.core.provider_ledger.credentials import claude_identity_path, read_claude_identity
from src.models.provider_ledger import AccountUsage, LedgerSnapshot

logger = structlog.get_logger()

ONBOARDING_KEY = "hasCompletedOnboarding"

OAUTH_KEY = "oauthAccount"

MCP_KEY = shared_mcp.MCP_KEY

PROJECTS_KEY = "projects"
TRUST_KEY = "hasTrustDialogAccepted"

PROFILE_FILE_MODE = 0o600

FILE_QUIET_SECONDS = 5.0

CONVERGED = "converged"
WROTE = "wrote"
DEFERRED = "deferred"
RACED = "raced"
NOT_SIGNED_IN = "not_signed_in"
UNAVAILABLE = "unavailable"


def setup_done(account: ProviderAccount) -> bool:
    identity = read_claude_identity(profile_dir_for(account))
    return identity is not None and identity.setup_complete


def read_default_login() -> Dict[str, Any]:
    try:
        document = config_writer.read_config(claude_identity_path(DEFAULT_CLAUDE_CONFIG_DIR))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.debug("profile_setup_default_unreadable", error=type(exc).__name__)
        return {}
    return document if isinstance(document, dict) else {}


def trusted_projects(document: Any) -> List[str]:
    projects = document.get(PROJECTS_KEY) if isinstance(document, dict) else None
    if not isinstance(projects, dict):
        return []
    return [p for p, entry in projects.items()
            if isinstance(entry, dict) and entry.get(TRUST_KEY) is True]


def _with_trust(projects: Dict[str, Any], trusted: Iterable[str]) -> Tuple[Dict[str, Any], int]:
    updated = dict(projects)
    added = 0
    for path in trusted:
        entry = updated.get(path)
        if entry is None:
            updated[path] = {TRUST_KEY: True}
        elif isinstance(entry, dict) and entry.get(TRUST_KEY) is not True:
            updated[path] = {**entry, TRUST_KEY: True}
        else:
            continue
        added += 1
    return updated, added


def plan_update(
    document: Dict[str, Any],
    *,
    mark_setup: bool,
    shared: Optional[Dict[str, Any]] = None,
    kept: Optional[Iterable[str]] = None,
    trusted: Iterable[str] = (),
) -> Optional[Dict[str, Any]]:
    if not isinstance(document.get(OAUTH_KEY), dict):
        return None
    updated = dict(document)
    changed = False
    if mark_setup and updated.get(ONBOARDING_KEY) is not True:
        updated[ONBOARDING_KEY] = True
        changed = True
    own = updated.get(MCP_KEY)
    if kept is not None and shared and isinstance(own, dict):
        remaining, removed = shared_mcp.strip_copies(own, shared, kept)
        if removed:
            updated[MCP_KEY] = remaining
            changed = True
    projects = updated.get(PROJECTS_KEY, {})
    if isinstance(projects, dict):
        with_trust, added = _with_trust(projects, trusted)
        if added:
            updated[PROJECTS_KEY] = with_trust
            changed = True
    return updated if changed else None


def quiet_enough(profile: Optional[str], path: Path) -> bool:
    reason = refresh_guard.busy_reason(profile)
    if reason == refresh_guard.BUSY_REFRESH_LOCK:
        return False
    if reason == refresh_guard.BUSY_CLAUDE_RUNNING:
        try:
            return time.time() - path.stat().st_mtime >= FILE_QUIET_SECONDS
        except OSError:
            return False
    return True


def converge_profile(
    account: ProviderAccount,
    *,
    mark_setup: bool,
    shared: Optional[Dict[str, Any]] = None,
    kept: Optional[Iterable[str]] = None,
    trusted: Iterable[str] = (),
    quiet: Callable[[Optional[str], Path], bool] = quiet_enough,
) -> str:
    if account.provider != "claude" or not account.managed:
        return UNAVAILABLE
    profile = profile_dir_for(account)
    path = claude_identity_path(profile)
    try:
        current = config_writer.read_config(path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.debug("profile_setup_unreadable", account_id=account.id, error=type(exc).__name__)
        return UNAVAILABLE
    if not isinstance(current, dict) or not isinstance(current.get(OAUTH_KEY), dict):
        return NOT_SIGNED_IN
    trusted = list(trusted)
    plan = dict(mark_setup=mark_setup, shared=shared, kept=kept, trusted=trusted)
    if plan_update(current, **plan) is None:
        return CONVERGED
    if not quiet(profile, path):
        logger.debug("profile_setup_deferred", account_id=account.id)
        return DEFERRED
    changes: List[Tuple[bool, int, int]] = []

    def mutate(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updated = plan_update(document, **plan)
        if updated is not None:
            changes.append((
                document.get(ONBOARDING_KEY) is not True and updated.get(ONBOARDING_KEY) is True,
                _count(document, MCP_KEY) - _count(updated, MCP_KEY),
                len(trusted_projects(updated)) - len(trusted_projects(document)),
            ))
        return updated

    try:
        outcome = config_writer.commit(
            path, mutate, file_mode=PROFILE_FILE_MODE, external_writer=True
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("profile_setup_write_failed", account_id=account.id, error=type(exc).__name__)
        return UNAVAILABLE
    if outcome.status == config_writer.STALE_REVISION:
        logger.info("profile_setup_raced", account_id=account.id)
        return RACED
    if not outcome.wrote:
        return CONVERGED
    marked, removed, trusted_added = changes[-1] if changes else (False, 0, 0)
    logger.info(
        "provider_profile_converged",
        account_id=account.id,
        setup_marked=marked,
        mcp_servers_removed=removed,
        trust_added=trusted_added,
    )
    return WROTE


def _count(document: Dict[str, Any], key: str) -> int:
    value = document.get(key)
    return len(value) if isinstance(value, dict) else 0


def _profile_servers(account: ProviderAccount) -> Optional[Dict[str, Any]]:
    try:
        document = config_writer.read_config(claude_identity_path(profile_dir_for(account)))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict) or not isinstance(document.get(OAUTH_KEY), dict):
        return None
    servers = document.get(MCP_KEY, {})
    return servers if isinstance(servers, dict) else None


def converge(
    rows: Iterable[AccountUsage],
    accounts: List[ProviderAccount],
    *,
    converge_one: Callable[..., str] = converge_profile,
) -> Dict[str, str]:
    ok = {row.id for row in rows if row.provider == "claude" and row.credential_state == "ok"}
    wanted = [a for a in accounts if a.id in ok and a.provider == "claude" and a.managed]
    if not wanted:
        return {}
    default = read_default_login()
    profiles = {a.id: servers for a in wanted
                if (servers := _profile_servers(a)) is not None}
    shared, kept = shared_mcp.sync(shared_mcp.default_servers(default), profiles)
    trusted = trusted_projects(default)
    return {
        a.id: converge_one(a, mark_setup=True, shared=shared, kept=kept.get(a.id), trusted=trusted)
        for a in wanted
    }


def mark_relay_setup(config_dir: str) -> bool:
    path = claude_identity_path(config_dir)
    try:
        if config_writer.create_if_absent(path, {ONBOARDING_KEY: True}, file_mode=PROFILE_FILE_MODE):
            return True
        outcome = config_writer.commit(
            path,
            lambda doc: None if doc.get(ONBOARDING_KEY) is True else {**doc, ONBOARDING_KEY: True},
            file_mode=PROFILE_FILE_MODE, external_writer=True,
        )
    except (OSError, ValueError) as exc:
        logger.warning("relay_profile_setup_failed", error=type(exc).__name__)
        return False
    return outcome.wrote


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


async def after_pass(
    snapshot: LedgerSnapshot,
    app_state: Any = None,
    *,
    config_path: Callable[[], Path] = _config_path,
    list_accounts: Callable[[Path], List[ProviderAccount]] = accounts_store.list_accounts,
) -> Dict[str, str]:
    try:
        accounts = await asyncio.to_thread(list_accounts, config_path())
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("profile_setup_config_unreadable", error=type(exc).__name__)
        return {}
    return await asyncio.to_thread(converge, snapshot.accounts, accounts)


__all__ = [
    "mark_relay_setup",
    "CONVERGED",
    "DEFERRED",
    "FILE_QUIET_SECONDS",
    "NOT_SIGNED_IN",
    "PROFILE_FILE_MODE",
    "RACED",
    "UNAVAILABLE",
    "WROTE",
    "after_pass",
    "converge",
    "converge_profile",
    "plan_update",
    "read_default_login",
    "setup_done",
    "trusted_projects",
]
