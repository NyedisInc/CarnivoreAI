
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, NamedTuple, Optional, Set

import structlog

from src.config import settings
from src.config.provider_accounts import profile_dir_for
from src.core.claude_config import accounts_folder_cache
from src.core.provider_ledger import accounts_store
from src.core.provider_ledger.relay_accounts import CODEX_RELAY_GLOB, CODEX_RELAY_NAME_RE

logger = structlog.get_logger()


class CodexAccountHome(NamedTuple):

    managed_account_id: Optional[str]
    path: Path


def codex_account_homes(config_path: Path) -> List[CodexAccountHome]:
    homes: List[CodexAccountHome] = []
    try:
        accounts = accounts_store.list_accounts(config_path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("codex_homes_config_unreadable", error=type(exc).__name__,
                       note="configured Codex account homes are skipped this pass; relayed folders are still read")
        accounts = []
    for account in accounts:
        if account.provider != "codex":
            continue
        profile = profile_dir_for(account)
        if profile:
            homes.append(CodexAccountHome(account.id if account.managed else None, Path(os.path.expanduser(profile))))
    relayed = accounts_folder_cache.listed_dirs(CODEX_RELAY_GLOB, lambda name: CODEX_RELAY_NAME_RE.fullmatch(name) is not None)
    homes.extend(CodexAccountHome(None, folder) for folder in relayed)
    return _unique_by_real_path(homes, set())


def account_homes_beside(default: Path, config_path: Optional[Path] = None) -> List[CodexAccountHome]:
    config = Path(config_path or settings.auth_config_file).expanduser()
    return _unique_by_real_path((h for h in codex_account_homes(config) if _is_dir(h.path)), {os.path.realpath(default)})


def _unique_by_real_path(homes: Iterable[CodexAccountHome], seen: Set[str]) -> List[CodexAccountHome]:
    unique: List[CodexAccountHome] = []
    for home in homes:
        real = os.path.realpath(home.path)
        if real not in seen:
            seen.add(real)
            unique.append(home)
    return unique


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError as exc:
        logger.debug("codex_homes_unstatable", path=str(path), error=type(exc).__name__)
        return False
