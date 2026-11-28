
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Collection, Dict, List, Optional, Set

import structlog

from src.core.pack.relay import codex_target, ledger_sync_store, target_side

logger = structlog.get_logger()

REMOVED, NOTHING, DEFERRED = "removed", "nothing", "deferred"
PROVIDERS = ("claude", "codex")
_DEFERRED_SEEN: Set[tuple] = set()


def _dir_and_state(provider: str, sender: str, account_key: str, home: Optional[Path]) -> tuple:
    if provider == "codex":
        folder = codex_target.codex_relay_profile_dir(account_key, sender, home)
        return folder, codex_target._existing_state(Path(folder) / codex_target.AUTH_FILE)
    from src.core.provider_ledger.credentials import claude_keychain_services

    folder = target_side.relay_profile_dir(account_key, sender, home)
    return folder, target_side._existing_state(claude_keychain_services(folder)[0])


def _has_conversations(folder: Path, provider: str = "claude") -> bool:
    subdirs = ("sessions", "archived_sessions") if provider == "codex" else ("projects",)
    return any(files for sub in subdirs for _root, _dirs, files in os.walk(folder / sub))


def _retire_sync(sender: str, account_key: str, provider: str, home: Optional[Path]) -> str:
    revoke = codex_target.revoke_codex if provider == "codex" else target_side.revoke
    gone = bool(revoke(sender, account_key, home=home))
    folder, state = _dir_and_state(provider, sender, account_key, home)
    path = Path(folder)
    if state == "absent" and path.is_dir() and not path.is_symlink() and not _has_conversations(path, provider):
        shutil.rmtree(path, ignore_errors=True)
        gone = gone or not path.exists()
    ledger_sync_store.forget(sender, provider, account_key)
    return REMOVED if gone else NOTHING


async def _in_use(manager: Any, sender: str, account_key: str, providers: Collection[str]) -> bool:
    from src.core.account_switch import pane_account
    from src.core.provider_ledger import relay_accounts

    ids = {(target_side.relay_profile_name if p == "claude" else codex_target.codex_relay_profile_name)(account_key, sender) for p in providers}
    held = [a for a in relay_accounts.with_relay([]) if a.id in ids]
    if not held:
        return False
    if manager is None:
        return True
    try:
        infos = await manager.list_session_infos()
        for account in held:
            if await pane_account.sessions_on_account(infos, socket=manager.tmux_socket_name(), accounts=held, account_id=account.id):
                return True
    except (OSError, RuntimeError) as exc:
        logger.warning("pack_relay_retire_listing_failed", error=type(exc).__name__)
        return True
    return False


async def retire(manager: Any, sender: str, account_key: str, providers: Collection[str] = PROVIDERS, *, home: Optional[Path] = None) -> str:
    if await _in_use(manager, sender, account_key, providers):
        if (sender, account_key) not in _DEFERRED_SEEN:
            _DEFERRED_SEEN.add((sender, account_key))
            logger.info("pack_relay_retire_deferred", sender=sender, account=account_key)
        return DEFERRED
    _DEFERRED_SEEN.discard((sender, account_key))
    outcomes = [await asyncio.to_thread(_retire_sync, sender, account_key, p, home) for p in providers]
    return REMOVED if REMOVED in outcomes else NOTHING


def stranded_keys(sender: str, offered: Collection[str]) -> List[str]:
    from src.core.provider_ledger import relay_accounts

    prefix = hashlib.sha256(sender.encode("utf-8")).hexdigest()[:12]
    keys: Dict[str, None] = {}
    for account in relay_accounts.with_relay([]):
        pattern = relay_accounts.CODEX_RELAY_NAME_RE if account.provider == "codex" else relay_accounts.RELAY_NAME_RE
        match = pattern.fullmatch(account.id)
        if match and match.group(1) == prefix and match.group(2) not in offered:
            keys[match.group(2)] = None
    return list(keys)


async def reconcile(manager: Any, sender: str, offered: Collection[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in stranded_keys(sender, set(offered)):
        try:
            out[key] = await retire(manager, sender, key)
        except target_side.RelayRefused as exc:
            logger.warning("pack_relay_reconcile_failed", sender=sender, account=key, code=exc.code)
    if REMOVED in out.values():
        logger.info("pack_relay_reconciled", sender=sender, removed=sorted(k for k, v in out.items() if v == REMOVED))
    return out
