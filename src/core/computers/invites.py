
from __future__ import annotations

import base64
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

INVITE_LIFE_S = 900.0
MAX_LIVE = 4
ATTEMPTS = 3
WRONG_CODE_CAP = 10
WRONG_CODE_WINDOW_S = 3600.0
CODE_PAUSE_S = 3600.0
KINDS = ("code", "ssh_add")


class MemberRefused(RuntimeError):
    pass


class TooManyInvites(RuntimeError):
    pass


@dataclass
class Invite:

    id: str
    code: Optional[str]
    secret: bytes
    kind: str
    job_id: Optional[str]
    created_at: float
    expires_at: float
    attempts_left: int = ATTEMPTS
    used: bool = False

    @property
    def link_secret(self) -> str:
        return base64.b32encode(self.secret).decode("ascii").lower().rstrip("=")


def secret_from_link(text: str) -> Optional[bytes]:
    if not isinstance(text, str) or len(text) != 32:
        return None
    try:
        return base64.b32decode(text.upper())
    except ValueError:
        return None


class Invites:

    def __init__(self, *, clock: Callable[[], float] = time.time,
                 on_change: Optional[Callable[[], None]] = None,
                 on_notice: Optional[Callable[[str, str], None]] = None,
                 is_member: Callable[[], bool] = lambda: False) -> None:
        self._is_member = is_member
        self._clock = clock
        self._on_change = on_change
        self._on_notice = on_notice
        self._lock = threading.RLock()
        self._items: List[Invite] = []
        self._wrong: Deque[float] = deque()
        self.code_paused_until: float = 0.0

    def _changed(self) -> None:
        if self._on_change:
            self._on_change()

    def _notice(self, event: str, addr: str) -> None:
        if self._on_notice:
            self._on_notice(event, addr)

    def _drop(self, inv: Invite) -> None:
        inv.secret = b""
        inv.code = None
        if inv in self._items:
            self._items.remove(inv)

    def _expire(self, now: float) -> bool:
        gone = [i for i in self._items if i.expires_at <= now or i.used]
        for inv in gone:
            self._drop(inv)
        return bool(gone)

    def code_paused(self) -> bool:
        return self._clock() < self.code_paused_until

    def mint(self, kind: str = "code", job_id: Optional[str] = None) -> Invite:
        if self._is_member():
            raise MemberRefused("a member computer mints no invites")
        if kind not in KINDS:
            raise ValueError("unknown invite kind")
        with self._lock:
            now = self._clock()
            self._expire(now)
            if len(self._items) >= MAX_LIVE:
                victim = next((i for i in self._items if i.kind == "code"), None)
                if victim is None:
                    raise TooManyInvites("four invites are already live")
                self._drop(victim)
            code = None
            if kind == "code" and not self.code_paused():
                code = f"{secrets.randbelow(10 ** 6):06d}"
                for old in self._items:
                    old.code = None
            inv = Invite(id=secrets.token_hex(4), code=code, secret=secrets.token_bytes(20), kind=kind,
                         job_id=job_id, created_at=now, expires_at=now + INVITE_LIFE_S)
            self._items.append(inv)
        self._changed()
        return inv

    def take_attempt(self, mode: str, invite_id: Optional[str] = None) -> Optional[Invite]:
        with self._lock:
            now = self._clock()
            if self._expire(now):
                self._changed()
            inv: Optional[Invite] = None
            if mode == "code":
                if not self.code_paused():
                    inv = next((i for i in self._items if i.code is not None and i.attempts_left > 0), None)
            elif mode == "invite":
                inv = next((i for i in self._items if i.id == invite_id and i.attempts_left > 0), None)
            if inv is None:
                return None
            inv.attempts_left -= 1
            return inv

    def finish_attempt(self, inv: Invite, *, ok: bool, mode: str, addr: str = "") -> int:
        notices: List[str] = []
        with self._lock:
            now = self._clock()
            left = inv.attempts_left
            if ok:
                inv.used = True
                self._drop(inv)
                left = 0
            else:
                counted = mode == "code"
                if inv.attempts_left <= 0:
                    self._drop(inv)
                    notices.append("burned")
                if counted:
                    self._wrong.append(now)
                    while self._wrong and self._wrong[0] <= now - WRONG_CODE_WINDOW_S:
                        self._wrong.popleft()
                    if len(self._wrong) >= WRONG_CODE_CAP:
                        self.code_paused_until = now + CODE_PAUSE_S
                        self._wrong.clear()
                        for i in self._items:
                            i.code = None
                        notices.append("paused")
        for event in notices:
            self._notice(event, addr)
        self._changed()
        return left

    def refund_attempt(self, inv: Invite) -> None:
        with self._lock:
            if inv in self._items and inv.attempts_left < ATTEMPTS:
                inv.attempts_left += 1

    def sweep(self) -> bool:
        with self._lock:
            gone = self._expire(self._clock())
        if gone:
            self._changed()
        return gone

    def cancel(self, invite_id: str) -> bool:
        with self._lock:
            inv = next((i for i in self._items if i.id == invite_id), None)
            if inv is None:
                return False
            self._drop(inv)
        self._changed()
        return True

    def cancel_job(self, job_id: str) -> int:
        with self._lock:
            mine = [i for i in self._items if i.job_id == job_id]
            for inv in mine:
                self._drop(inv)
        if mine:
            self._changed()
        return len(mine)

    def any_live(self) -> bool:
        with self._lock:
            self._expire(self._clock())
            return bool(self._items)

    def live(self) -> List[Invite]:
        with self._lock:
            self._expire(self._clock())
            return list(self._items)
