
from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.computers import join_proto
from src.core.computers.invites import Invite, Invites, MemberRefused, TooManyInvites
from src.core.computers.join_limits import KnockRates

log = structlog.get_logger(__name__)

LABEL_MAX = 40
BLOCK_SECONDS = 600.0
FID_SHORT = 6


def clean_label(raw: str, fid: str) -> str:
    kept = "".join(ch for ch in raw if not unicodedata.category(ch).startswith("C") and unicodedata.category(ch) not in ("Zl", "Zp"))
    text = " ".join(kept.split())[:LABEL_MAX].strip()
    return text or f"computer {fid[:FID_SHORT]}"


@dataclass(frozen=True)
class Knock:

    fid: str
    iid: str
    label: str

    @classmethod
    def from_message(cls, fields: Dict[str, str]) -> "Knock":
        return cls(fields["fid"], fields["iid"], clean_label(fields["label"], fields["fid"]))


@dataclass
class _Entry:

    id: str
    fid: str
    iid: str
    label: str
    addr: str
    created_at: float


class KnockDesk:

    def __init__(self, invites: Invites, own_label: str, *, clock: Callable[[], float] = time.time, notify: Callable[[str], None] = lambda _t: None,
                 emit: Callable[[str, str, str], bool] = lambda _l, _a, _k: False, rates: Optional[KnockRates] = None) -> None:
        self._inv, self._label, self._clock, self._notify, self._emit = invites, own_label, clock, notify, emit
        self._rates = rates or KnockRates()
        self._entries: Dict[str, _Entry] = {}
        self._blocked: Dict[str, float] = {}

    def _live(self) -> List[tuple]:
        by_id = {i.id: i for i in self._inv.live()}
        for gone in [k for k in self._entries if k not in by_id]:
            del self._entries[gone]
        return [(e, by_id[e.id]) for e in self._entries.values()]

    def _is_blocked(self, fid: str, now: float) -> bool:
        for key in [k for k, until in self._blocked.items() if until <= now]:
            del self._blocked[key]
        return fid in self._blocked

    def _ok(self, inv: Invite, now: float) -> Dict[str, Any]:
        return join_proto.knock_ok(main_label=self._label, expires_in=max(1, int(inv.expires_at - now)), knock_id=inv.id)

    async def handle(self, knock: Knock, addr: str) -> Dict[str, Any]:
        now = self._clock()
        if not self._rates.admit(addr):
            return join_proto.error("rate_limited")
        if self._is_blocked(knock.fid, now) or self._is_blocked(addr, now):
            return join_proto.error("refused")
        pending = self._live()
        mine = next(((e, i) for e, i in pending if e.fid == knock.fid), None)
        if mine is not None:
            return self._ok(mine[1], now)
        if pending:
            return join_proto.error("busy")
        if any(i.kind == "code" and i.code is not None for i in self._inv.live()):
            return join_proto.error("busy")
        if self._inv.code_paused() or self._inv.knock_paused():
            return join_proto.error("paused")
        try:
            inv = self._inv.mint("code")
        except MemberRefused:
            return join_proto.error("refused")
        except TooManyInvites:
            return join_proto.error("busy")
        if inv.code is None:
            self._inv.cancel(inv.id)
            return join_proto.error("paused")
        inv.knock = True
        self._entries[inv.id] = _Entry(inv.id, knock.fid, knock.iid, knock.label, addr, now)
        log.info("computer_knock", knock_id=inv.id, addr=addr)
        self._notify("pack_knocks")
        self._emit(knock.label, addr, inv.id)
        return self._ok(inv, now)

    def pending(self) -> List[Dict[str, Any]]:
        return [{"id": e.id, "label": e.label, "addr": e.addr, "fid_short": e.fid[:FID_SHORT], "code": i.code, "expires_at": i.expires_at,
                 "attempts_left": i.attempts_left} for e, i in self._live()]

    def dismiss(self, knock_id: str) -> bool:
        entry = next((e for e, _i in self._live() if e.id == knock_id), None)
        if entry is None:
            return False
        self._blocked[entry.fid] = self._blocked[entry.addr] = self._clock() + BLOCK_SECONDS
        self._inv.cancel(entry.id)
        self._entries.pop(entry.id, None)
        log.info("computer_knock_dismissed", knock_id=knock_id)
        self._notify("pack_knocks")
        return True
