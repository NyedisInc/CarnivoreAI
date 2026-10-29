
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.config.provider_accounts import (
    PROVIDER_ACCOUNTS_KEY,
    ProviderAccount,
    ProviderAccountsConfig,
)
from src.core import config_writer, resource_push
from src.core.read_caches.config_stat import CONFIG_READS
from src.core.resource_push import topics as resource_topics

logger = structlog.get_logger()

ACCOUNTS_KEY = "accounts"


def read_block(config: Dict[str, Any]) -> List[ProviderAccount]:
    block = config.get(PROVIDER_ACCOUNTS_KEY)
    if not isinstance(block, dict):
        return []
    try:
        return list(ProviderAccountsConfig(**block).accounts)
    except (TypeError, ValueError):
        return []


def list_accounts(config_path: Path) -> List[ProviderAccount]:
    resolved = Path(config_path).expanduser()
    kept = CONFIG_READS.fetch(resolved, ACCOUNTS_KEY, lambda: tuple(_read_accounts(resolved)))
    return [account.model_copy(deep=True) for account in kept]


def _read_accounts(resolved: Path) -> List[ProviderAccount]:
    if not resolved.exists():
        raise FileNotFoundError(f"Auth config file not found: {resolved}")
    try:
        data = json.loads(resolved.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {resolved}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config shape in {resolved}: expected an object")
    return read_block(data)


def _write(
    config_path: Path,
    rewrite,
    *,
    event: str,
    **log_context: Any,
) -> Tuple[str, List[ProviderAccount]]:

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updated = rewrite(read_block(config))
        if updated is None:
            return None
        existing = config.get(PROVIDER_ACCOUNTS_KEY)
        block = dict(existing) if isinstance(existing, dict) else {}
        block[ACCOUNTS_KEY] = [account.model_dump() for account in updated]
        return {**config, PROVIDER_ACCOUNTS_KEY: block}

    outcome = config_writer.commit(Path(config_path).expanduser(), mutate)
    now = read_block(outcome.data)
    if outcome.wrote:
        resource_push.notify(resource_topics.PROVIDER_LEDGER)
        resource_push.notify(resource_topics.ACCOUNT_SWITCH)
        logger.info(event, accounts=len(now), **log_context)
    return outcome.status, now


def upsert_account(
    config_path: Path, account: ProviderAccount
) -> Tuple[str, List[ProviderAccount]]:

    def rewrite(current: List[ProviderAccount]) -> Optional[List[ProviderAccount]]:
        for existing in current:
            if existing.id == account.id and existing == account:
                return None
        replaced = [a for a in current if a.id == account.id]
        if replaced:
            return [account if a.id == account.id else a for a in current]
        return [*current, account]

    return _write(
        config_path,
        rewrite,
        event="provider_account_upserted",
        account_id=account.id,
        provider=account.provider,
    )


def remove_account(
    config_path: Path, account_id: str
) -> Tuple[str, List[ProviderAccount]]:

    def rewrite(current: List[ProviderAccount]) -> Optional[List[ProviderAccount]]:
        kept = [a for a in current if a.id != account_id]
        if len(kept) == len(current):
            return None
        return kept

    return _write(
        config_path,
        rewrite,
        event="provider_account_removed",
        account_id=account_id,
    )
