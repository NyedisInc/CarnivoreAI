
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Collection, Dict, List, Optional

from src.core.account_switch import profile_setup
from src.core.pack.relay import keychain_write
from src.core.provider_ledger import keychain
from src.core.provider_ledger.credentials import claude_keychain_services

ACCOUNT_KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
TOKEN_RE = re.compile(r"[\x21-\x7e]{20,1024}")
SCOPE_RE = re.compile(r"[A-Za-z0-9:_.-]{1,64}")
MIN_REMAINING_SECONDS = 60
MAX_REMAINING_SECONDS = 24 * 3600
MAX_DOCUMENT_BYTES = 1600
MARKER_KEY = "carnivoreRelay"


class RelayRefused(Exception):

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code, self.status = code, status


def relay_profile_name(account_key: str, sender_install_id: str) -> str:
    return f"{hashlib.sha256(sender_install_id.encode('utf-8')).hexdigest()[:12]}-{account_key}-relay"


def relay_profile_dir(account_key: str, sender_install_id: str, home: Optional[Path] = None) -> str:
    root = (home or Path.home()) / ".carnivore" / "accounts" / relay_profile_name(account_key, sender_install_id)
    return unicodedata.normalize("NFC", str(root))


def find_relay_profile(account_key: str, home: Optional[Path] = None) -> Optional[str]:
    if not ACCOUNT_KEY_RE.fullmatch(account_key):
        return None
    root = (home or Path.home()) / ".carnivore" / "accounts"
    try:
        found = [p for p in root.glob(f"????????????-{account_key}-relay") if p.is_dir() and re.fullmatch(r"[0-9a-f]{12}", p.name[:12])]
    except OSError:
        return None
    return unicodedata.normalize("NFC", str(max(found, key=lambda p: p.stat().st_mtime))) if found else None


def build_document(access_token: str, expires_at_ms: int, *, scopes: List[str], subscription_type: Optional[str],
                   rate_limit_tier: Optional[str], sender_install_id: str) -> str:
    oauth: Dict[str, Any] = {"accessToken": access_token, "expiresAt": expires_at_ms, "scopes": scopes}
    if subscription_type:
        oauth["subscriptionType"] = subscription_type
    if rate_limit_tier:
        oauth["rateLimitTier"] = rate_limit_tier
    return json.dumps({"claudeAiOauth": oauth, MARKER_KEY: {"from": sender_install_id}}, separators=(",", ":"))


def _has_refresh_token(node: Any) -> bool:
    if isinstance(node, dict):
        return any(re.sub(r"[_-]", "", str(k)).lower() == "refreshtoken" or _has_refresh_token(v) for k, v in node.items())
    if isinstance(node, list):
        return any(_has_refresh_token(v) for v in node)
    return False


def _existing_state(service: str) -> str:
    raw = keychain.read_password(service, account=keychain_write.keychain_account())
    if raw is None:
        return "absent"
    try:
        doc = json.loads(raw)
    except ValueError:
        return "foreign"
    marker = doc.get(MARKER_KEY) if isinstance(doc, dict) else None
    if _has_refresh_token(doc) or not isinstance(marker, dict) or not isinstance(marker.get("from"), str):
        return "foreign"
    return "mine:" + marker["from"]


def receive(sender_install_id: str, account_key: str, profile: str, access_token: str, expires_at_ms: int, *,
            scopes: List[str], subscription_type: Optional[str] = None, rate_limit_tier: Optional[str] = None,
            reserved_names: Collection[str] = (), reserved_services: Collection[str] = (),
            home: Optional[Path] = None, security_bin: str = keychain_write.SECURITY_BIN,
            now: Optional[float] = None, authorize: Optional[Callable[[], bool]] = None) -> int:
    if not ACCOUNT_KEY_RE.fullmatch(account_key or ""):
        raise RelayRefused("bad_account")
    name = relay_profile_name(account_key, sender_install_id)
    if profile != name:
        raise RelayRefused("bad_profile")
    if not isinstance(access_token, str) or not TOKEN_RE.fullmatch(access_token):
        raise RelayRefused("bad_token")
    if not all(isinstance(x, str) and SCOPE_RE.fullmatch(x) for x in scopes):
        raise RelayRefused("bad_scopes")
    clock = now if now is not None else time.time()
    if not isinstance(expires_at_ms, int) or isinstance(expires_at_ms, bool) \
            or not (clock + MIN_REMAINING_SECONDS) * 1000 <= expires_at_ms <= (clock + MAX_REMAINING_SECONDS) * 1000:
        raise RelayRefused("expired")
    config_dir = relay_profile_dir(account_key, sender_install_id, home)
    service = claude_keychain_services(config_dir)[0]
    if name in reserved_names or service in reserved_services:
        raise RelayRefused("relay_profile_conflict", 409)
    document = build_document(access_token, expires_at_ms, scopes=scopes, subscription_type=subscription_type,
                              rate_limit_tier=rate_limit_tier, sender_install_id=sender_install_id)
    if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise RelayRefused("too_large")
    state = _existing_state(service)
    if state == "foreign":
        raise RelayRefused("relay_profile_conflict", 409)
    if state != "absent" and state != "mine:" + sender_install_id:
        raise RelayRefused("relay_peer_conflict", 409)
    if authorize is not None and not authorize():
        raise RelayRefused("relay_not_accepted", 403)
    try:
        os.makedirs(config_dir, mode=0o700, exist_ok=True)
    except OSError:
        raise RelayRefused("write_failed", 503) from None
    try:
        keychain_write.write_item(service, document, update=state != "absent", security_bin=security_bin)
    except keychain_write.KeychainWriteError as exc:
        raise RelayRefused("too_large" if exc.code == "too_large" else f"write_{exc.code}",
                           422 if exc.code == "too_large" else 503) from None
    profile_setup.mark_relay_setup(config_dir)
    return expires_at_ms


def revoke(sender_install_id: str, account_key: str, *, home: Optional[Path] = None,
           security_bin: str = keychain_write.SECURITY_BIN) -> bool:
    if not ACCOUNT_KEY_RE.fullmatch(account_key or ""):
        raise RelayRefused("bad_account")
    service = claude_keychain_services(relay_profile_dir(account_key, sender_install_id, home))[0]
    if _existing_state(service) != "mine:" + sender_install_id:
        return False
    try:
        keychain_write.delete_item(service, security_bin=security_bin)
    except keychain_write.KeychainWriteError as exc:
        raise RelayRefused(f"write_{exc.code}", 503) from None
    return True
