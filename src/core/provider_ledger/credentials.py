"""Reading the LIVE Claude and Codex credential stores, never writing one.

**AND IT MUST NOT REFRESH, WHICH IS A STRONGER RULE THAN "NEED NOT".**
The Claude access token lives about eight hours and its refresh token is
SINGLE USE; Codex rotates its refresh token and OpenAI detects reuse and
says so in as many words. Either refresh performed here would spend the
token the user's own CLI is holding and log them out of it. So an expired
credential is a REPORTED STATE, and ``claude`` or ``codex`` renews it on
their own schedule, usually within seconds.

**NEVER FALL BACK FROM A PROFILE TO THE DEFAULT LOGIN.** A custom
``CLAUDE_CONFIG_DIR`` is an isolated profile with its own keychain item,
and Claude Code itself ignores the default login inside one. A reader
that fell back would report account A's usage under account B's name,
which is worse than reporting nothing, so an account that resolves to
nothing resolves to ``None``.

**THE KEYCHAIN SERVICE NAME FOR A PROFILE IS SETTLED**: it is
``sha256(NFC(the raw CLAUDE_CONFIG_DIR string))[:8]``, read out of
Claude Code 2.1.266's own bundle. A second candidate is still tried for
hand-written tilde rows; see :func:`claude_keychain_services`.

**NOTHING HERE LOGS A TOKEN, AND NOTHING PRINTS ONE EITHER.** The
credential dataclasses declare their token fields ``repr=False`` AND
carry an explicit ``__repr__``, because a dataclass repr reaches a
traceback, a debugger and any log line that formats the object. ``str``
is deliberately not defined a second time: python falls back to
``__repr__`` for it, so one definition covers both and they cannot drift.

**EVERY READ IS TOLERANT AND NONE OF THEM RAISES.** A missing file, a
mangled one, a keychain that refuses, a JWT that will not decode: each
costs one reading and resolves to ``None`` or to an absent field. An
absent field means COULD NOT BE DETERMINED and never zero.

THIS MODULE IS THE PUBLIC SURFACE. The Codex reader lives in
:mod:`src.core.provider_ledger.codex_credentials` because the pair
passed the 500-line guideline, and is re-exported here so a caller needs
one import.
"""

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

# CLAUDE_CONFIG_DIR
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
        logger.info("claude_credential_without_oauth_block", source=source)
        return None

    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        logger.info("claude_credential_without_access_token", source=source)
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


def read_claude_credential(config_dir: str) -> Optional[ClaudeCredential]:
    return claude_store.read_freshest(
        claude_keychain_services(config_dir),
        _read_claude_keychain,
        lambda: _read_claude_file(config_dir),
        datetime.now(timezone.utc),
    )


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
    """Whether every value this credential puts in a header is ascii.

    Description: an http header value is encoded as ascii by httpx, so a
      stored value carrying anything else raises ``UnicodeEncodeError``
      while the request is being built. That is a ``ValueError`` and NOT
      an ``httpx.RequestError``, so it escapes both fetchers' catch
      ladders and reaches the polling loop's outermost frame, which is
      the wrong place to discover it: the exception's own message names
      the offending character and its offset, which is one character of
      a credential per pass. Measured here instead, and never sent.
    Inputs: credential (ClaudeCredential | CodexCredential) - the values
      the fetchers read their headers out of.
    Output: bool - False when any of them could not be sent.
    Example: _sendable_as_header(credential)  # True
    """
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
    """Parse one json file, or report that it could not be parsed.

    Description: absent, unreadable and malformed all answer ``None``,
      because a reading this app could not take must never become a
      fabricated value. The three are told apart in the log, not in the
      return.
    Inputs: path (Path) - the file to read.
    Output: the parsed document, or None.
    """
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
