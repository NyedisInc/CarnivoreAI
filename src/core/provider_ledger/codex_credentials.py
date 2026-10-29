
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.provider_ledger import keychain
from src.core.provider_ledger.miss_cache import MissCache
from src.core.provider_ledger.codex_usage import (
    account_id_from_id_token,
    plan_type_from_id_token,
)
from src.core.provider_ledger.credential_values import (
    epoch_seconds_to_datetime,
    jwt_claims,
    optional_str,
    parse_iso,
)

logger = structlog.get_logger()

CODEX_KEYCHAIN_SERVICE = "Codex Auth"
CODEX_AUTH_FILE = "auth.json"

_misses = MissCache("codex_credential_missing")

CODEX_PROFILE_CLAIM = "https://api.openai.com/profile"


@dataclass(frozen=True, repr=False)
class CodexCredential:

    access_token: str = field(repr=False)
    id_token: Optional[str] = field(repr=False)
    account_id: Optional[str]
    plan: Optional[str]
    email: Optional[str]
    last_refresh: Optional[datetime]
    expires_at: Optional[datetime]
    source: str

    def __repr__(self) -> str:
        return (
            "CodexCredential("
            f"source={self.source!r}, account_id={self.account_id!r}, "
            f"plan={self.plan!r}, email={self.email!r}, "
            f"last_refresh={self.last_refresh!r}, expires_at={self.expires_at!r}, "
            "access_token=<hidden>, id_token=<hidden>)"
        )


def codex_keychain_account(codex_home: str) -> str:
    canonical = os.path.realpath(os.path.expanduser(codex_home))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"cli|{digest[:16]}"


def parse_codex_document(document: Any, *, source: str) -> Optional[CodexCredential]:
    if not isinstance(document, dict):
        return None
    tokens = document.get("tokens")
    if not isinstance(tokens, dict):
        logger.info("codex_credential_without_tokens", source=source)
        return None

    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        logger.info("codex_credential_without_access_token", source=source)
        return None

    id_token = optional_str(tokens.get("id_token"))
    claims = jwt_claims(id_token)
    profile_claim = claims.get(CODEX_PROFILE_CLAIM)
    profile_claim = profile_claim if isinstance(profile_claim, dict) else {}

    return CodexCredential(
        access_token=access,
        id_token=id_token,
        account_id=(
            optional_str(tokens.get("account_id"))
            or (account_id_from_id_token(id_token) if id_token else None)
        ),
        plan=plan_type_from_id_token(id_token) if id_token else None,
        email=(
            optional_str(claims.get("email"))
            or optional_str(profile_claim.get("email"))
        ),
        last_refresh=parse_iso(document.get("last_refresh")),
        expires_at=epoch_seconds_to_datetime(jwt_claims(access).get("exp")),
        source=source,
    )


def read_codex_credential(codex_home: str) -> Optional[CodexCredential]:
    path = Path(os.path.expanduser(codex_home)) / CODEX_AUTH_FILE
    try:
        raw = path.read_text()
    except FileNotFoundError:
        raw = None
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("codex_auth_file_unreadable", error=type(exc).__name__)
        return None

    if raw is not None:
        return parse_codex_document(_loads(raw, source="file"), source="file")

    home = path.parent
    try:
        st = home.stat()
        stamp: tuple = ((st.st_mtime_ns, st.st_size),)
    except OSError:
        stamp = (None,)
    if _misses.blocked(str(home), stamp):
        return None
    from_keychain = keychain.read_password(
        CODEX_KEYCHAIN_SERVICE, account=codex_keychain_account(codex_home)
    )
    if not from_keychain:
        _misses.miss(str(home), stamp)
        return None
    _misses.hit(str(home))
    return parse_codex_document(
        _loads(from_keychain, source="keychain"), source="keychain"
    )


def _loads(raw: str, *, source: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.info("codex_credential_unparseable", source=source)
        return None
