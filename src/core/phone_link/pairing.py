
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

WINDOW_SECONDS = 600
QR_SECRET_SECONDS = 120
QR_ROTATE_SECONDS = 60
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
MAX_CODE_MISSES = 5
PENDING_SECONDS = 300
MAX_PENDING_ATTEMPTS = 5
MAX_FAILED_PAIRINGS = 2
FAILURE_WINDOW_SECONDS = 3600
IP_MISS_LIMIT = 10
IP_MISS_INTERVAL_SECONDS = 600
IP_TABLE_MAX = 4096
LABEL_MAX = 40
SEEN_WRITE_SECONDS = 60.0


class Throttled(Exception):
    pass


class PairingLocked(Exception):
    pass


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class _Code:

    digest: str
    expires: float
    kind: str
    misses: int = 0


@dataclass(frozen=True)
class Window:

    secret: str
    code: str
    expires_at: float
    secret_expires_at: float


@dataclass(frozen=True)
class Claim:

    device_id: str
    label: str
    kind: str
    created_at: int


@dataclass
class _Pending:

    label: str
    expires: float
    attempts: int = 0


@dataclass(frozen=True)
class ClaimResult:

    handle: Optional[str]
    status: str


@dataclass
class Device:

    id: str
    label: str
    kind: str
    created_at: int
    last_seen: Optional[int] = None


class PairingStore:

    def __init__(self, *, path: Path, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        path.chmod(0o600)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, label TEXT NOT NULL,"
            " kind TEXT NOT NULL, cookie_hash TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL);")
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(devices)")}
        if "last_seen" not in columns:
            self._db.execute("ALTER TABLE devices ADD COLUMN last_seen INTEGER")
        if "host" not in columns:
            self._db.execute("ALTER TABLE devices ADD COLUMN host TEXT NOT NULL DEFAULT ''")
        self._seen_written: Dict[str, float] = {}
        self._cookies: Dict[str, Tuple[str, str]] = {
            h: (i, host) for i, h, host in self._db.execute("SELECT id, cookie_hash, host FROM devices")}
        self._codes: List[_Code] = []
        self.last_claim: Optional[Claim] = None
        self._window_expires = 0.0
        self._pending: Dict[str, _Pending] = {}
        self._failures: List[float] = []
        self.last_failed = False
        self._claim_expires = 0.0
        self._misses: Dict[str, Deque[float]] = defaultdict(deque)
        self.on_revoke: List[Callable[[str], None]] = []

    def close(self) -> None:
        with self._lock:
            self._db.close()


    @property
    def enabled(self) -> bool:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()
        return bool(row and row[0] == "1")

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('enabled', ?)",
                             ("1" if value else "0",))

    def setting(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))


    def _prune(self) -> None:
        now = self._clock()
        self._codes = [c for c in self._codes if c.expires > now]

    def open_window(self) -> Window:
        with self._lock:
            if self.locked():
                raise PairingLocked()
            self.last_failed = False
            self._codes = []
            self._pending = {}
            self.last_claim = None
            secret = secrets.token_urlsafe(32)
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            now = self._clock()
            expires = now + WINDOW_SECONDS
            self._window_expires = expires
            secret_expires = min(expires, now + QR_SECRET_SECONDS)
            self._codes.append(_Code(_digest(secret), secret_expires, "window_secret"))
            self._codes.append(_Code(_digest(code), expires, "window_code"))
        logger.info("phone_link_window_opened")
        return Window(secret, code, expires, secret_expires)

    def locked(self) -> bool:
        with self._lock:
            cutoff = self._clock() - FAILURE_WINDOW_SECONDS
            self._failures = [t for t in self._failures if t > cutoff]
            return len(self._failures) >= MAX_FAILED_PAIRINGS

    def acknowledge_failures(self) -> None:
        with self._lock:
            self._failures = []
            self.last_failed = False

    def _kill_spent(self, key: str) -> None:
        del self._pending[key]
        self._failures.append(self._clock())
        self.last_failed = True
        logger.warning("phone_link_pairing_spent")

    def rotate_secret(self) -> Optional[Tuple[str, float]]:
        with self._lock:
            self._prune()
            if not self.window_open():
                return None
            secrets_live = [c for c in self._codes if c.kind == "window_secret"]
            self._codes = [c for c in self._codes if c.kind != "window_secret"] + secrets_live[-1:]
            secret = secrets.token_urlsafe(32)
            expires = min(self._window_expires, self._clock() + QR_SECRET_SECONDS)
            self._codes.append(_Code(_digest(secret), expires, "window_secret"))
            return secret, expires

    def window_open(self) -> bool:
        with self._lock:
            return self._clock() < self._window_expires

    def _end_window(self) -> None:
        self._codes = []
        self._window_expires = 0.0

    def close_window(self) -> None:
        with self._lock:
            self._end_window()
            self._pending = {}

    def _live_pending(self) -> Dict[str, _Pending]:
        now = self._clock()
        self._pending = {k: v for k, v in self._pending.items() if v.expires > now}
        return self._pending

    def pairing_view(self) -> Dict[str, object]:
        with self._lock:
            locked = self.locked()
            if self.window_open():
                return {"state": "open", "device": None, "locked": locked}
            if self._live_pending():
                return {"state": "pending", "device": None, "locked": locked}
            if self.last_claim is not None and self._clock() < self._claim_expires:
                return {"state": "claimed", "device": vars(self.last_claim), "locked": locked}
            self.last_claim = None
            return {"state": "failed" if self.last_failed else "none", "device": None, "locked": locked}

    def _throttle(self, ip: str) -> None:
        now = self._clock()
        cutoff = now - IP_MISS_INTERVAL_SECONDS
        for key in [k for k, q in self._misses.items() if not q or q[-1] <= cutoff]:
            del self._misses[key]
        misses = self._misses.get(ip)
        if misses is None:
            return
        while misses and misses[0] <= cutoff:
            misses.popleft()
        if len(misses) >= IP_MISS_LIMIT:
            raise Throttled(ip)

    def _redeem(self, presented: str, kinds: tuple, ip: str) -> Optional[_Code]:
        self._prune()
        self._throttle(ip)
        is_secret = kinds == ("window_secret",)
        digest = _digest(presented.strip() if is_secret else presented.strip().upper())
        hit = next((c for c in self._codes if c.kind in kinds
                    and hmac.compare_digest(c.digest, digest)), None)
        if hit is not None:
            return hit
        self._misses[ip].append(self._clock())
        while len(self._misses) > IP_TABLE_MAX:
            del self._misses[min(self._misses, key=lambda k: self._misses[k][-1])]
        for code in self._codes:
            if code.kind in kinds and not is_secret:
                code.misses += 1
        self._codes = [c for c in self._codes if c.misses < MAX_CODE_MISSES]
        logger.warning("phone_link_pair_miss")
        return None

    def _live_device(self, cookie: Optional[str], host: str, legacy_host: str) -> Optional[str]:
        return self.device_for_cookie(cookie, host, legacy_host) if cookie else None

    def _begin_pending(self, label: str) -> ClaimResult:
        self._end_window()
        handle = secrets.token_urlsafe(32)
        clean = "".join(ch for ch in label if ch.isprintable())[:LABEL_MAX] or "phone"
        self._pending[_digest(handle)] = _Pending(clean, self._clock() + PENDING_SECONDS)
        logger.info("phone_link_pairing_pending")
        return ClaimResult(handle, "pending")

    def claim_secret(self, secret: str, ip: str, label: str = "phone", host: str = "",
                     current_cookie: Optional[str] = None, legacy_host: str = "") -> Optional[ClaimResult]:
        with self._lock:
            if self._live_device(current_cookie, host, legacy_host) is not None:
                return ClaimResult(None, "already_paired")
            if self._redeem(secret, ("window_secret",), ip) is None:
                return None
            return self._begin_pending(label)

    def claim_code(self, code: str, ip: str, label: str = "phone", host: str = "",
                   current_cookie: Optional[str] = None, legacy_host: str = "") -> Optional[ClaimResult]:
        with self._lock:
            if self._redeem(code, ("window_code",), ip) is None:
                return None
            if self._live_device(current_cookie, host, legacy_host) is not None:
                return ClaimResult(None, "already_paired")
            return self._begin_pending(label)

    def pending_open(self) -> bool:
        with self._lock:
            return bool(self._live_pending())

    def has_pending(self, handle: Optional[str]) -> bool:
        with self._lock:
            return bool(handle) and _digest(handle or "") in self._live_pending()

    def begin_attempt(self, handle: Optional[str]) -> Optional[int]:
        with self._lock:
            key = _digest(handle or "")
            pending = self._live_pending().get(key)
            if pending is None:
                return None
            if pending.attempts >= MAX_PENDING_ATTEMPTS:
                self._kill_spent(key)
                return None
            pending.attempts += 1
            return MAX_PENDING_ATTEMPTS - pending.attempts

    def drop_if_spent(self, handle: Optional[str]) -> bool:
        with self._lock:
            pending = self._pending.get(_digest(handle or ""))
            if pending is None or pending.attempts < MAX_PENDING_ATTEMPTS:
                return pending is None
            self._kill_spent(_digest(handle or ""))
            return True

    def complete_pending(self, handle: Optional[str], host: str = "") -> Optional[str]:
        with self._lock:
            pending = self._live_pending().pop(_digest(handle or ""), None)
            if pending is None:
                return None
            cookie, device_id = self._mint(pending.label, "browser", host)
            now = self._clock()
            self.last_claim = Claim(device_id, pending.label, "browser", int(now))
            self._claim_expires = now + WINDOW_SECONDS
            return cookie


    def _mint(self, label: str, kind: str, host: str = "") -> Tuple[str, str]:
        cookie = secrets.token_urlsafe(32)
        device_id = secrets.token_hex(8)
        clean = "".join(ch for ch in label if ch.isprintable())[:LABEL_MAX] or "phone"
        digest = _digest(cookie)
        self._db.execute("INSERT INTO devices(id, label, kind, cookie_hash, created_at, host)"
                         " VALUES(?,?,?,?,?,?)", (device_id, clean, kind, digest, int(self._clock()), host.lower()))
        self._cookies[digest] = (device_id, host.lower())
        logger.info("phone_link_device_paired", device=device_id, kind=kind)
        return cookie, device_id

    def device_for_cookie(self, cookie: str, host: Optional[str] = None, legacy_host: str = "") -> Optional[str]:
        bound = self._cookies.get(_digest(cookie))
        if bound is None:
            return None
        issued_on = bound[1] or legacy_host.lower()
        if host is not None and issued_on and issued_on != host.lower():
            return None
        return bound[0]

    def touch(self, device_id: str) -> None:
        now = self._clock()
        with self._lock:
            if now - self._seen_written.get(device_id, 0.0) < SEEN_WRITE_SECONDS:
                return
            self._seen_written[device_id] = now
            try:
                self._db.execute("UPDATE devices SET last_seen=? WHERE id=?", (int(now), device_id))
            except sqlite3.Error as exc:
                logger.warning("phone_link_touch_failed", device=device_id, error=str(exc))

    def devices(self) -> List[Device]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, label, kind, created_at, last_seen FROM devices ORDER BY created_at, id").fetchall()
        return [Device(*row) for row in rows]

    def devices_off_link(self, link_host: str) -> List[Device]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, label, kind, created_at, last_seen FROM devices WHERE host != '' AND host != ?"
                " ORDER BY created_at, id", (link_host.lower(),)).fetchall()
        return [Device(*row) for row in rows]

    def device_count(self) -> int:
        return len(self._cookies)

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT cookie_hash FROM devices WHERE id=?", (device_id,)).fetchone()
            if row is None:
                return False
            self._db.execute("DELETE FROM devices WHERE id=?", (device_id,))
            self._cookies.pop(row[0], None)
            self._seen_written.pop(device_id, None)
            if self.last_claim is not None and self.last_claim.device_id == device_id:
                self.last_claim = None
        logger.info("phone_link_device_revoked", device=device_id)
        for hook in list(self.on_revoke):
            hook(device_id)
        return True
