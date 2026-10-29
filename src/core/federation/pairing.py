
from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Dict, Optional

import structlog

logger = structlog.get_logger()

PROTOCOL_MAJOR = 1
ANSWER_ALL_MINOR = 3
FOLDER_BROWSE_MINOR = 4
UPLOAD_MINOR = 5
SCREENS_MINOR = 6
PROTOCOL_MINOR = 6
PROOF_SSH_FILE = "ssh_file"
PROOF_TYPED = "typed"
FILE_TTL_SECONDS = 5 * 60
TYPED_TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5
BEGIN_PER_MINUTE = 5
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
FILE_DIR_NAME = "federation"
FILE_PREFIX = "pair-"


class PairError(Exception):

    code = "pair_code_invalid"


class RateLimited(Exception):
    pass


class SlidingWindow:

    def __init__(self, limit: int, seconds: float) -> None:
        self._limit, self._seconds = limit, seconds
        self._events: Deque[float] = deque()

    def hit(self, now: float) -> bool:
        while self._events and self._events[0] <= now - self._seconds:
            self._events.popleft()
        if len(self._events) >= self._limit:
            return False
        self._events.append(now)
        return True


class KeyedWindows:

    def __init__(self, limit: int, seconds: float, max_keys: int = 2048) -> None:
        self._limit, self._seconds, self._max = limit, seconds, max_keys
        self._windows: Dict[str, SlidingWindow] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float) -> bool:
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                if len(self._windows) >= self._max:
                    self._windows.pop(next(iter(self._windows)))
                window = self._windows[key] = SlidingWindow(self._limit, self._seconds)
            return window.hit(now)


@dataclass
class Offer:

    nonce: str
    proof: str
    expires: float
    attempts: int = 0
    path: Optional[Path] = None
    _code: str = ""

    def __repr__(self) -> str:
        return f"Offer(nonce={self.nonce!r}, proof={self.proof!r})"

    @property
    def code(self) -> str:
        return self._code


def _write_code_file(state_dir: Path, nonce: str, code: str) -> Path:
    directory = state_dir / FILE_DIR_NAME
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / f"{FILE_PREFIX}{nonce}"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(code + "\n")
    return path


def _remove(path: Optional[Path]) -> None:
    if path is not None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class PairingOffers:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._offers: Dict[str, Offer] = {}
        self._windows: Dict[str, SlidingWindow] = {}
        self._lock = threading.Lock()

    def begin(self, proof: str, state_dir: Path) -> Offer:
        with self._lock:
            now = self._clock()
            if not self._windows.setdefault(proof, SlidingWindow(BEGIN_PER_MINUTE, 60.0)).hit(now):
                raise RateLimited()
            self._drop(proof)
            nonce = secrets.token_hex(8)
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            ttl = FILE_TTL_SECONDS if proof == PROOF_SSH_FILE else TYPED_TTL_SECONDS
            path = _write_code_file(state_dir, nonce, code) if proof == PROOF_SSH_FILE else None
            offer = self._offers[proof] = Offer(nonce=nonce, proof=proof, expires=now + ttl, path=path, _code=code)
            return offer

    def redeem(self, nonce: object, code: object) -> Offer:
        with self._lock:
            for proof in list(self._offers):
                if self._clock() >= self._offers[proof].expires:
                    self._drop(proof)
            if not (isinstance(nonce, str) and isinstance(code, str)):
                raise PairError()
            offer = next((o for o in self._offers.values()
                          if hmac.compare_digest(nonce.encode(), o.nonce.encode())), None)
            if offer is None:
                raise PairError()
            offer.attempts += 1
            if not hmac.compare_digest(code.strip().upper().encode(), offer.code.encode()):
                if offer.attempts >= MAX_ATTEMPTS:
                    self._drop(offer.proof)
                raise PairError()
            self._drop(offer.proof)
            return offer

    def outstanding(self) -> bool:
        with self._lock:
            return any(self._clock() < o.expires for o in self._offers.values())

    def _drop(self, proof: str) -> None:
        offer = self._offers.pop(proof, None)
        if offer is not None:
            _remove(offer.path)


OFFERS = PairingOffers()


@dataclass(frozen=True)
class PairPlan:

    proof: str
    back_route: str


def plan_pairing(*, host_key_pinned_before: bool, fid_matches_pinned: bool,
                 ssh_user_matches: bool) -> PairPlan:
    trusted_first_contact = host_key_pinned_before or fid_matches_pinned
    typed = not trusted_first_contact or not ssh_user_matches
    return PairPlan(PROOF_TYPED if typed else PROOF_SSH_FILE, "unix" if ssh_user_matches else "tcp")
