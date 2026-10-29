
from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

import structlog

from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR
from src.core.provider_ledger import claude_store, keychain
from src.core.provider_ledger.miss_cache import MissCache
from src.core.provider_ledger.codex_credentials import (
    CODEX_AUTH_FILE,
    CODEX_KEYCHAIN_SERVICE,
    CodexCredential,
    codex_keychain_account,
    read_codex_credential,
)
from src.core.provider_ledger.credential_values import (
    epoch_millis_to_datetime,
    optional_str,
)

logger = structlog.get_logger()

__all__ = [
    "CLAUDE_CREDENTIALS_FILE",
    "CLAUDE_IDENTITY_FILE",
    "CLAUDE_KEYCHAIN_SERVICE",
    "CLAUDE_USAGE_SCOPE",
    "CODEX_AUTH_FILE",
    "CODEX_KEYCHAIN_SERVICE",
    "ClaudeCredential",
    "ClaudeIdentity",
    "CodexCredential",
    "claude_identity_path",
    "claude_keychain_services",
    "codex_keychain_account",
    "credential_state_for",
    "is_default_claude_dir",
    "read_claude_credential",
    "read_claude_identity",
    "read_codex_credential",
]

CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"

CLAUDE_CREDENTIALS_FILE = ".credentials.json"

CLAUDE_IDENTITY_FILE = ".claude.json"

CLAUDE_USAGE_SCOPE = "user:profile"


@dataclass(frozen=True, repr=False)
class ClaudeCredential:

    access_token: str = field(repr=False)
    expires_at: Optional[datetime]
    refresh_token_expires_at: Optional[datetime]
    scopes: Tuple[str, ...]
    subscription_type: Optional[str]
    rate_limit_tier: Optional[str]
    source: str
    has_refresh_token: bool = False

    def __repr__(self) -> str:
        return (
            "ClaudeCredential("
            f"source={self.source!r}, expires_at={self.expires_at!r}, "
            f"refresh_token_expires_at={self.refresh_token_expires_at!r}, "
            f"scopes={self.scopes!r}, subscription_type={self.subscription_type!r}, "
            f"rate_limit_tier={self.rate_limit_tier!r}, access_token=<hidden>)"
        )


@dataclass(frozen=True)
class ClaudeIdentity:

    email: Optional[str]
    organization_name: Optional[str]
    subscription_type: Optional[str]
    setup_complete: bool = False


AnyCredential = Union[ClaudeCredential, CodexCredential]


def is_default_claude_dir(config_dir: str) -> bool:
    return os.path.normpath(os.path.expanduser(config_dir)) == os.path.normpath(
        os.path.expanduser(DEFAULT_CLAUDE_CONFIG_DIR)
    )


def claude_keychain_services(config_dir: str) -> List[str]:
    if is_default_claude_dir(config_dir):
        return [CLAUDE_KEYCHAIN_SERVICE]

    candidates = [config_dir, os.path.realpath(os.path.expanduser(config_dir))]
    services: List[str] = []
    for candidate in candidates:
        raw = unicodedata.normalize("NFC", candidate)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        name = f"{CLAUDE_KEYCHAIN_SERVICE}-{digest}"
        if name not in services:
            services.append(name)
    return services


def _parse_claude_blob(raw: str, *, source: str) -> Optional[ClaudeCredential]:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("claude_credential_unparseable", source=source)
        return None

    oauth = document.get("claudeAiOauth") if isinstance(document, dict) else None
    if not isinstance(oauth, dict):
        logger.debug("claude_credential_without_oauth_block", source=source)
        return None

    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        logger.debug("claude_credential_without_access_token", source=source)
        return None

    raw_scopes = oauth.get("scopes")
    scopes = tuple(str(s) for s in raw_scopes) if isinstance(raw_scopes, list) else ()

    return ClaudeCredential(
        access_token=token,
        expires_at=epoch_millis_to_datetime(oauth.get("expiresAt")),
        refresh_token_expires_at=epoch_millis_to_datetime(
            oauth.get("refreshTokenExpiresAt")
        ),
        scopes=scopes,
        subscription_type=optional_str(oauth.get("subscriptionType")),
        rate_limit_tier=optional_str(oauth.get("rateLimitTier")),
        source=source,
        has_refresh_token=bool(oauth.get("refreshToken")),
    )


def _read_claude_keychain(service: str, account: Optional[str]) -> Optional[ClaudeCredential]:
    raw = keychain.read_password(service, account=account)
    return _parse_claude_blob(raw, source="keychain") if raw else None


def _read_claude_file(config_dir: str) -> Optional[ClaudeCredential]:
    path = Path(os.path.expanduser(config_dir)) / CLAUDE_CREDENTIALS_FILE
    try:
        raw_file = path.read_text()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("claude_credential_file_unreadable", error=type(exc).__name__)
        return None
    return _parse_claude_blob(raw_file, source="file")


_misses = MissCache("claude_credential_missing")


def _login_stamp(config_dir: str) -> tuple:
    base = Path(os.path.expanduser(config_dir))
    stamps = []
    for path in (claude_identity_path(config_dir), base / CLAUDE_CREDENTIALS_FILE, base):
        try:
            st = path.stat()
            stamps.append((st.st_mtime_ns, st.st_size))
        except OSError:
            stamps.append(None)
    return tuple(stamps)


def read_claude_credential(config_dir: str) -> Optional[ClaudeCredential]:
    stamp = _login_stamp(config_dir)
    if _misses.blocked(config_dir, stamp):
        return None
    credential = claude_store.read_freshest(
        claude_keychain_services(config_dir),
        _read_claude_keychain,
        lambda: _read_claude_file(config_dir),
        datetime.now(timezone.utc),
    )
    if credential is not None:
        _misses.hit(config_dir)
        return credential
    _misses.miss(config_dir, stamp)
    return None


def claude_identity_path(config_dir: str) -> Path:
    if is_default_claude_dir(config_dir):
        return Path(os.path.expanduser("~")) / CLAUDE_IDENTITY_FILE
    return Path(os.path.expanduser(config_dir)) / CLAUDE_IDENTITY_FILE


def read_claude_identity(config_dir: str) -> Optional[ClaudeIdentity]:
    document = _load_json_file(claude_identity_path(config_dir))
    if not isinstance(document, dict):
        return None
    account = document.get("oauthAccount")
    if not isinstance(account, dict):
        return None
    return ClaudeIdentity(
        email=optional_str(account.get("emailAddress")),
        organization_name=optional_str(account.get("organizationName")),
        subscription_type=optional_str(account.get("subscriptionType")),
        setup_complete=document.get("hasCompletedOnboarding") is True,
    )


def _sendable_as_header(credential: AnyCredential) -> bool:
    values = [credential.access_token]
    if isinstance(credential, CodexCredential):
        values.append(credential.account_id)
    return all(value.isascii() for value in values if value)


def credential_state_for(credential: Optional[AnyCredential], now: datetime) -> str:
    if credential is None:
        return "missing"
    if credential.expires_at is not None and credential.expires_at <= now:
        return "expired"
    if not _sendable_as_header(credential):
        logger.info(
            "provider_ledger_credential_not_transmittable", source=credential.source
        )
        return "error"
    if isinstance(credential, ClaudeCredential):
        if credential.scopes and CLAUDE_USAGE_SCOPE not in credential.scopes:
            return "refused"
    return "ok"


def _load_json_file(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("credential_file_unreadable", error=type(exc).__name__)
        return None
    except json.JSONDecodeError:
        logger.info("credential_file_unparseable")
        return None
