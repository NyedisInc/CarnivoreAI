
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal, Optional

import structlog

from src.core.account_switch import codex_follow, session_pin, store
from src.core.account_switch.active import effective_active, find_account
from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR, profile_dir_for
from src.core.pack.jobs.agent_types import ACCOUNT_KEY_PATTERN
from src.core.pack.jobs.types import JobError
from src.core.pack.move import account as move_account
from src.core.pack.relay import codex_target
from src.core.provider_ledger.credentials import read_claude_identity

log = structlog.get_logger(__name__)

_KEY = re.compile(ACCOUNT_KEY_PATTERN)
DEFAULT_LABEL = "default login"
HOW_WORDS = {"same": "the same login as the caller's", "relay": "the relay copy of the caller's login",
             "local": "a local login with the same name", "fallback": "this computer's active login"}


@dataclass(frozen=True)
class AccountPick:

    account_id: Optional[str]
    extra_env: Dict[str, str] = field(default_factory=dict)
    label: str = DEFAULT_LABEL
    how: Literal["same", "relay", "local", "fallback"] = "same"


def _not_usable(family: str) -> JobError:
    return JobError(move_account.NOT_USABLE_CODE, f"no {family} login on this computer can run this job; log in here or relay the account first", 409)


def _local_how(identity: Optional[str], local_identity: Optional[str]) -> Literal["same", "local"]:
    if identity is None:
        return "same"
    return "same" if identity and local_identity and identity == local_identity.strip().lower() else "local"


def _claude_identity(account_id: Optional[str], config_path: Path) -> Optional[str]:
    try:
        account = find_account(session_pin.all_accounts(config_path), account_id, move_account.PROVIDER) if account_id else None
        got = read_claude_identity(profile_dir_for(account) if account is not None else DEFAULT_CLAUDE_CONFIG_DIR)
    except (FileNotFoundError, ValueError, OSError):
        return None
    return got.email.strip().lower() if got is not None and got.email else None


def _claude(account_key: Optional[str], caller_install_id: Optional[str], config_path: Path, identity: Optional[str] = None) -> AccountPick:
    found = move_account.launch_for(account_key, caller_install_id, config_path)
    if found is not None:
        env = dict(found.get("extra_env") or {})
        how = "relay" if env else _local_how(identity, _claude_identity(found.get("account_id"), config_path) if identity else None)
        return AccountPick(found.get("account_id"), env, account_key or DEFAULT_LABEL, how)
    try:
        active = effective_active(session_pin.all_accounts(config_path), store.read_switch(config_path), move_account.PROVIDER).account_id
    except (FileNotFoundError, ValueError, OSError) as exc:
        log.warning("pack_jobs_agent_account_unreadable", error=type(exc).__name__)
        active = None
    for key in (active, None):
        if key == account_key:
            continue
        found = move_account.launch_for(key, None, config_path)
        if found is not None:
            env = dict(found.get("extra_env") or {})
            return AccountPick(found.get("account_id"), env, key or DEFAULT_LABEL, "fallback")
    raise _not_usable("claude")


def _codex(account_key: Optional[str], caller_install_id: Optional[str], config_path: Path, identity: Optional[str] = None) -> AccountPick:
    if account_key:
        profile = codex_target.codex_relay_profile_dir(account_key, caller_install_id) if caller_install_id else codex_target.find_codex_relay_profile(account_key)
        if profile and Path(profile).is_dir():
            return AccountPick(None, codex_target.codex_relay_env(profile), account_key, "relay")
        try:
            local = find_account(session_pin.all_accounts(config_path), account_key, "codex")
        except (FileNotFoundError, ValueError, OSError):
            local = None
        if local is not None and session_pin.is_launchable(local):
            return AccountPick(account_key, {}, account_key, _local_how(identity, None))
    try:
        followed = codex_follow.follow_active_account(config_path)
    except codex_follow.CodexAccountRefused as exc:
        raise JobError(move_account.NOT_USABLE_CODE, str(exc), 409) from exc
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise _not_usable("codex") from exc
    return AccountPick(followed, {}, followed or DEFAULT_LABEL, "fallback")


def resolve_target_account(family: str, account_key: Optional[str], caller_install_id: Optional[str], config_path: Path,
                           caller_identity: Optional[str] = None) -> AccountPick:
    if family not in ("claude", "codex"):
        raise JobError("bad_family", "the worker family must be claude or codex", 422)
    if account_key is not None and not _KEY.fullmatch(account_key):
        raise JobError(move_account.NOT_USABLE_CODE, "the account key is not a valid account name", 409)
    return (_claude if family == "claude" else _codex)(account_key, caller_install_id, config_path, caller_identity)
