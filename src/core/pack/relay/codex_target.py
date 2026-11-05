
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Collection, Dict, Optional

from src.core.pack.relay.target_side import (ACCOUNT_KEY_RE, MARKER_KEY, MIN_REMAINING_SECONDS, RelayRefused,
                                              _has_refresh_token)
from src.core.provider_ledger.credential_values import jwt_claims

JWT_RE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
ACCOUNT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
MAX_JWT_CHARS = 8192
MAX_REMAINING_SECONDS = 30 * 24 * 3600
AUTH_FILE = "auth.json"
RELAY_SUFFIX = "-relay-codex"
DEAD_REFRESH_URL = "https://127.0.0.1:1/carnivore-relay-no-refresh"
DEAD_REVOKE_URL = "https://127.0.0.1:1/carnivore-relay-no-revoke"


def codex_relay_profile_name(account_key: str, sender_install_id: str) -> str:
    return f"{hashlib.sha256(sender_install_id.encode('utf-8')).hexdigest()[:12]}-{account_key}{RELAY_SUFFIX}"


def codex_relay_profile_dir(account_key: str, sender_install_id: str, home: Optional[Path] = None) -> str:
    root = (home or Path.home()) / ".carnivore" / "accounts" / codex_relay_profile_name(account_key, sender_install_id)
    return unicodedata.normalize("NFC", str(root))


def find_codex_relay_profile(account_key: str, home: Optional[Path] = None) -> Optional[str]:
    if not ACCOUNT_KEY_RE.fullmatch(account_key):
        return None
    root = (home or Path.home()) / ".carnivore" / "accounts"
    try:
        found = [p for p in root.glob(f"????????????-{account_key}{RELAY_SUFFIX}")
                 if p.is_dir() and re.fullmatch(r"[0-9a-f]{12}", p.name[:12])]
    except OSError:
        return None
    return unicodedata.normalize("NFC", str(max(found, key=lambda p: p.stat().st_mtime))) if found else None


def codex_relay_env(codex_home: str) -> Dict[str, str]:
    return {"CODEX_HOME": codex_home, "CODEX_REFRESH_TOKEN_URL_OVERRIDE": DEAD_REFRESH_URL,
            "CODEX_REVOKE_TOKEN_URL_OVERRIDE": DEAD_REVOKE_URL}


def build_document(access_token: str, id_token: str, account_id: str, sender_install_id: str, now: float) -> str:
    stamp = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None,
                       "tokens": {"id_token": id_token, "access_token": access_token, "refresh_token": "",
                                  "account_id": account_id},
                       "last_refresh": stamp, MARKER_KEY: {"from": sender_install_id}}, separators=(",", ":"))


def _existing_state(path: Path) -> str:
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return "foreign"
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "absent"
    except (OSError, ValueError):
        return "foreign"
    marker = doc.get(MARKER_KEY) if isinstance(doc, dict) else None
    tokens = doc.get("tokens") if isinstance(doc, dict) else None
    if not isinstance(marker, dict) or not isinstance(marker.get("from"), str) or not isinstance(tokens, dict) \
            or tokens.get("refresh_token") != "" or _has_refresh_token({k: v for k, v in doc.items() if k != "tokens"}):
        return "foreign"
    return "mine:" + marker["from"]


def _write_atomic(directory: str, document: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".auth-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, os.path.join(directory, AUTH_FILE))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def receive_codex(sender_install_id: str, account_key: str, profile: str, access_token: str, id_token: str, account_id: str,
                  expires_at_ms: int, *, reserved_names: Collection[str] = (), reserved_homes: Collection[str] = (),
                  home: Optional[Path] = None, now: Optional[float] = None,
                  authorize: Optional[Callable[[], bool]] = None) -> int:
    if not ACCOUNT_KEY_RE.fullmatch(account_key or ""):
        raise RelayRefused("bad_account")
    name = codex_relay_profile_name(account_key, sender_install_id)
    if profile != name:
        raise RelayRefused("bad_profile")
    for token in (access_token, id_token):
        if not isinstance(token, str) or len(token) > MAX_JWT_CHARS or not JWT_RE.fullmatch(token):
            raise RelayRefused("bad_token")
    if not isinstance(account_id, str) or not ACCOUNT_ID_RE.fullmatch(account_id):
        raise RelayRefused("bad_account_id")
    clock = now if now is not None else time.time()
    if not isinstance(expires_at_ms, int) or isinstance(expires_at_ms, bool) \
            or not (clock + MIN_REMAINING_SECONDS) * 1000 <= expires_at_ms <= (clock + MAX_REMAINING_SECONDS) * 1000:
        raise RelayRefused("expired")
    exp = jwt_claims(access_token).get("exp")
    if isinstance(exp, (int, float)) and abs(exp * 1000 - expires_at_ms) > 2000:
        raise RelayRefused("bad_token")
    config_dir = codex_relay_profile_dir(account_key, sender_install_id, home)
    if name in reserved_names or os.path.realpath(config_dir) in reserved_homes:
        raise RelayRefused("relay_profile_conflict", 409)
    path = Path(config_dir) / AUTH_FILE
    state = _existing_state(path)
    if state == "foreign":
        raise RelayRefused("relay_profile_conflict", 409)
    if state != "absent" and state != "mine:" + sender_install_id:
        raise RelayRefused("relay_peer_conflict", 409)
    if authorize is not None and not authorize():
        raise RelayRefused("relay_not_accepted", 403)
    try:
        os.makedirs(config_dir, mode=0o700, exist_ok=True)
        os.chmod(config_dir, 0o700)
        _write_atomic(config_dir, build_document(access_token, id_token, account_id, sender_install_id, clock))
    except OSError:
        raise RelayRefused("write_failed", 503) from None
    return expires_at_ms


def revoke_codex(sender_install_id: str, account_key: str, *, home: Optional[Path] = None) -> bool:
    if not ACCOUNT_KEY_RE.fullmatch(account_key or ""):
        raise RelayRefused("bad_account")
    path = Path(codex_relay_profile_dir(account_key, sender_install_id, home)) / AUTH_FILE
    if _existing_state(path) != "mine:" + sender_install_id:
        return False
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    except OSError:
        raise RelayRefused("write_failed", 503) from None
    return True
