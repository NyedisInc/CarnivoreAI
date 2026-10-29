
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.config.provider_accounts import (
    DEFAULT_CLAUDE_CONFIG_DIR,
    DEFAULT_CODEX_HOME,
    ProviderAccount,
)
from src.core.provider_ledger.codex_credentials import CODEX_AUTH_FILE
from src.core.provider_ledger.codex_usage import (
    account_id_from_id_token,
    user_id_from_id_token,
)
from src.core.provider_ledger.credential_values import optional_str
from src.core.provider_ledger.credentials import (
    claude_identity_path,
    is_default_claude_dir,
)

logger = structlog.get_logger()

LoginIdentity = Tuple[str, Optional[str]]

_IDENTITY_CACHE: Dict[str, Tuple[Tuple[int, int], Optional[LoginIdentity]]] = {}


_CODEX_ID_CACHE: Dict[str, Tuple[Tuple[int, int], Optional[str]]] = {}


def canonical_path(path: str) -> Optional[str]:
    try:
        return os.path.realpath(str(Path(path).expanduser()))
    except (OSError, ValueError, RuntimeError) as exc:
        logger.debug("session_account_path_unresolved", error=str(exc))
        return None


def pointer_of(account: ProviderAccount) -> str:
    return (
        account.claude_config_dir
        if account.provider == "claude"
        else account.codex_home
    )


def accounts_pointing_at_default(
    accounts: List[ProviderAccount], *, provider: str
) -> List[ProviderAccount]:
    default = canonical_path(
        DEFAULT_CLAUDE_CONFIG_DIR if provider == "claude" else DEFAULT_CODEX_HOME
    )
    if default is None:
        return []
    matched = []
    for account in accounts:
        if account.provider != provider:
            continue
        if canonical_path(pointer_of(account)) == default:
            matched.append(account)
    return matched


def _parse_login_identity(identity_file: Path) -> Optional[LoginIdentity]:
    try:
        document = json.loads(identity_file.read_text())
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.info(
            "session_account_identity_unreadable",
            file=str(identity_file),
            error=type(exc).__name__,
        )
        return None
    account = document.get("oauthAccount") if isinstance(document, dict) else None
    uuid = account.get("accountUuid") if isinstance(account, dict) else None
    if not isinstance(uuid, str) or not uuid:
        logger.info("session_account_identity_absent", file=str(identity_file))
        return None
    org = account.get("organizationUuid")
    return (uuid, org if isinstance(org, str) and org else None)


def login_identity(identity_file: Path) -> Optional[LoginIdentity]:
    try:
        info = identity_file.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.info(
            "session_account_identity_unreadable",
            file=str(identity_file),
            error=type(exc).__name__,
        )
        return None
    stamp = (info.st_mtime_ns, info.st_size)
    key = str(identity_file)
    cached = _IDENTITY_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    identity = _parse_login_identity(identity_file)
    _IDENTITY_CACHE[key] = (stamp, identity)
    return identity


def claude_accounts_matching_default_identity(
    accounts: List[ProviderAccount],
) -> List[ProviderAccount]:
    default = login_identity(claude_identity_path(DEFAULT_CLAUDE_CONFIG_DIR))
    if default is None:
        return []
    return [
        account
        for account in accounts
        if account.provider == "claude"
        and not is_default_claude_dir(account.claude_config_dir)
        and login_identity(claude_identity_path(account.claude_config_dir))
        == default
    ]


def default_login_is_configured(accounts: List[ProviderAccount]) -> bool:
    return bool(
        accounts_pointing_at_default(accounts, provider="claude")
        or claude_accounts_matching_default_identity(accounts)
    )


def _parse_codex_account_id(auth_file: Path) -> Optional[str]:
    try:
        document = json.loads(auth_file.read_text())
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.info(
            "session_account_identity_unreadable",
            file=str(auth_file),
            error=type(exc).__name__,
        )
        return None
    tokens = document.get("tokens") if isinstance(document, dict) else None
    if not isinstance(tokens, dict):
        return None
    id_token = tokens.get("id_token")
    user = user_id_from_id_token(id_token) if isinstance(id_token, str) else None
    if user is None:
        return None
    workspace = optional_str(tokens.get("account_id")) or account_id_from_id_token(id_token)
    if workspace is None:
        return None
    return f"{workspace}/{user}"


def codex_login_id(codex_home: str) -> Optional[str]:
    auth_file = Path(codex_home).expanduser() / CODEX_AUTH_FILE
    try:
        info = auth_file.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.info(
            "session_account_identity_unreadable",
            file=str(auth_file),
            error=type(exc).__name__,
        )
        return None
    stamp = (info.st_mtime_ns, info.st_size)
    key = str(auth_file)
    cached = _CODEX_ID_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    found = _parse_codex_account_id(auth_file)
    _CODEX_ID_CACHE[key] = (stamp, found)
    return found


def codex_accounts_matching_default_identity(
    accounts: List[ProviderAccount],
) -> List[ProviderAccount]:
    default = codex_login_id(DEFAULT_CODEX_HOME)
    if default is None:
        return []
    default_dir = canonical_path(DEFAULT_CODEX_HOME)
    return [
        account
        for account in accounts
        if account.provider == "codex"
        and canonical_path(account.codex_home) != default_dir
        and codex_login_id(account.codex_home) == default
    ]
