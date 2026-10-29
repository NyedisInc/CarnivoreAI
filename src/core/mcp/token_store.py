
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.safe_file_write import write_private_file

logger = structlog.get_logger()

PREFIX = "cmcp_"
FILE_NAME = "mcp_tokens.json"
SCOPES = ("read", "write")
MAX_TOKENS = 50
NAME_MAX = 60
EXPIRY_MAX_DAYS = 3650
_USED_FLUSH_SECONDS = 60.0


class TokenError(ValueError):
    pass


def _row_ok(r: Any) -> bool:
    return (isinstance(r, dict) and all(isinstance(r.get(k), str) and r[k] for k in ("hash", "id", "name"))
            and r.get("scope") in SCOPES and (r.get("expires_at") is None or isinstance(r.get("expires_at"), (int, float))))


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def is_token(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(PREFIX)


def public_view(rec: dict) -> dict:
    return {k: rec[k] for k in ("id", "name", "scope", "created_at", "last_used_at", "expires_at")}


class TokenStore:

    def __init__(self, directory: Path, clock=time.time) -> None:
        self._dir = directory
        self._clock = clock
        self._lock = threading.Lock()
        self._rows: list[dict] = []
        self._io_lock = threading.Lock()
        self._flushed: dict[str, float] = {}
        self.refused = ""
        path = directory / FILE_NAME
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            return
        except OSError as exc:
            self.refused = f"the token file cannot be read ({type(exc).__name__})"
        else:
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                self.refused = "the token file is a link or not a regular file"
            elif mode & 0o077:
                self.refused = "the token file is readable by other users (it must be mode 0600)"
        if not self.refused:
            try:
                rows = json.loads(path.read_text("utf-8")).get("tokens", [])
                self._rows = [r for r in rows if _row_ok(r)]
                if len(self._rows) != len(rows):
                    logger.error("mcp_tokens_rows_dropped", dropped=len(rows) - len(self._rows))
            except (OSError, ValueError, AttributeError, TypeError) as exc:
                self.refused = f"the token file is unreadable or malformed ({type(exc).__name__})"
        if self.refused:
            logger.error("mcp_tokens_refused", reason=self.refused)

    def _flush(self) -> None:
        with self._io_lock:
            with self._lock:
                data = json.dumps({"tokens": self._rows}, indent=1).encode("utf-8")
            write_private_file(self._dir, FILE_NAME, data, 0o600)

    def list(self) -> list[dict]:
        with self._lock:
            return [public_view(r) for r in self._rows]

    def mint(self, name: str, scope: str, expires_in_days: Optional[int] = None) -> tuple[dict, str]:
        if self.refused:
            raise TokenError(f"refused: {self.refused}")
        name = (name or "").strip()
        if not name or len(name) > NAME_MAX:
            raise TokenError(f"name must be 1 to {NAME_MAX} characters")
        if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in name):
            raise TokenError("name may not contain control, invisible or direction characters")
        if scope not in SCOPES:
            raise TokenError("scope must be read or write")
        if expires_in_days is not None and not (isinstance(expires_in_days, int) and not isinstance(expires_in_days, bool) and 1 <= expires_in_days <= EXPIRY_MAX_DAYS):
            raise TokenError(f"expiry must be 1 to {EXPIRY_MAX_DAYS} days")
        secret = PREFIX + secrets.token_urlsafe(32)
        now = self._clock()
        rec = {
            "id": "tok_" + secrets.token_hex(6), "name": name, "scope": scope, "hash": _hash(secret),
            "created_at": now, "last_used_at": None,
            "expires_at": None if expires_in_days is None else now + expires_in_days * 86400,
        }
        with self._lock:
            if len(self._rows) >= MAX_TOKENS:
                raise TokenError(f"at most {MAX_TOKENS} tokens; revoke one first")
            if any(r["name"].lower() == name.lower() for r in self._rows):
                raise TokenError("a token with that name exists")
            self._rows.append(rec)
        try:
            self._flush()
        except OSError:
            with self._lock:
                self._rows.remove(rec)
            raise
        logger.info("mcp_token_minted", token_name=name, scope=scope, token_id=rec["id"])
        return public_view(rec), secret

    def revoke(self, token_id: str) -> bool:
        if self.refused:
            raise TokenError(f"refused: {self.refused}")
        with self._lock:
            keep = [r for r in self._rows if r["id"] != token_id]
            if len(keep) == len(self._rows):
                return False
            gone = [r for r in self._rows if r["id"] == token_id][0]
            before, self._rows = self._rows, keep
        try:
            self._flush()
        except OSError:
            with self._lock:
                self._rows = before
            raise
        logger.info("mcp_token_revoked", token_name=gone["name"], token_id=token_id)
        return True

    def authenticate(self, secret: str) -> Optional[dict]:
        digest = _hash(secret)
        found: Optional[dict] = None
        with self._lock:
            for rec in self._rows:
                if hmac.compare_digest(rec["hash"], digest):
                    found = rec
            if found is None:
                return None
            now = self._clock()
            if found["expires_at"] is not None and now >= found["expires_at"]:
                return None
            found["last_used_at"] = now
            flush = now - self._flushed.get(found["id"], 0.0) >= _USED_FLUSH_SECONDS
            if flush:
                self._flushed[found["id"]] = now
            view = public_view(found)
        if flush:
            try:
                self._flush()
            except OSError as exc:
                logger.warning("mcp_token_used_unsaved", error=type(exc).__name__)
        return view


_stores: dict[str, TokenStore] = {}
_stores_lock = threading.Lock()


def get_store() -> TokenStore:
    from src.config import settings

    directory = settings.get_state_dir()
    with _stores_lock:
        store = _stores.get(str(directory))
        if store is None:
            store = _stores[str(directory)] = TokenStore(directory)
        return store
