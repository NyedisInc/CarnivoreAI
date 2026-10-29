
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Sequence, Tuple

import structlog
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from src.core.db import DatastoreUnreadableError
from src.core.federation import peer_fanout, peer_hosts
from src.core.stats_feed.model import Classes, PeerWord, WindowSpec, fold, merge

if TYPE_CHECKING:
    from src.core.stats_feed.feed import StatsFeed

logger = structlog.get_logger()

WIRE_VERSION = 1
PATH = "/stats/feed/local"
PULL_S: float = 5.0
STALE_S: float = 3600.0
FRESH_S: float = PULL_S + peer_fanout.DEADLINE_SECONDS + 5.0
SKEW_FLAG_S: float = 90.0
SKEW_ALPHA: float = 0.3
MAX_BUCKETS = 60
MAX_GAPS = 200
MAX_COUNT = 10**13
MAX_RATE = 1e12
OWN_WORDS = ("ok", "catching_up")
HELD_WORDS = ("paused", "plugin_off", "needs_approval")
FAILED = ("unreachable", "refused", "not_supported")

Int = StrictInt
Bucket = Tuple[Int, Int, Int, Int, Int]


class RateWire(BaseModel):
    """A peer's trailing rate: tokens per second by class on ITS clock."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    span_seconds: float = Field(ge=0, le=1e6)
    fresh: float = Field(ge=0, le=MAX_RATE)
    cache_write: float = Field(ge=0, le=MAX_RATE)
    cache_read: float = Field(ge=0, le=MAX_RATE)
    out: float = Field(ge=0, le=MAX_RATE)


class PeerAnswer(BaseModel):
    """What ``GET /stats/feed/local`` serves: one computer's OWN numbers. Anything else in the body is refused."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    v: Int
    install_id: str = Field(min_length=1, max_length=128)
    rev: Int = Field(ge=0, le=MAX_COUNT)
    now: float = Field(ge=0, le=1e11)
    state: Literal["ok", "catching_up", "stats_off", "paused", "plugin_off", "needs_approval", "unavailable"]
    data_through: Optional[float] = Field(default=None, ge=0, le=1e11)
    rate: Optional[RateWire] = None
    windows: Optional[Dict[Literal["1h", "5h", "1d", "7d"], List[Bucket]]] = None
    gaps: List[Tuple[Int, Optional[Int]]] = Field(default_factory=list, max_length=MAX_GAPS)

    @field_validator("windows")
    @classmethod
    def _bounded(cls, windows: Any) -> Any:
        for buckets in (windows or {}).values():
            if len(buckets) > MAX_BUCKETS:
                raise ValueError("too many buckets")
            if any(not 0 <= n <= MAX_COUNT for bucket in buckets for n in bucket):
                raise ValueError("bucket value out of range")
        return windows


@dataclass
class Imported:

    key: str
    label: str
    answer: Optional[PeerAnswer] = None
    good_mono: Optional[float] = None
    good_wall: Optional[float] = None
    state: PeerWord = "unreachable"
    reason: str = ""
    skew: Optional[float] = None


@dataclass
class PeerBook:

    items: Dict[str, Imported] = field(default_factory=dict)
    asked_mono: Optional[float] = None

    def signature(self) -> Tuple:
        return tuple(sorted((i.key, i.label, i.state, i.reason, i.answer is not None,
                             i.answer.rev if i.answer else None) for i in self.items.values()))


@dataclass(frozen=True)
class Merged:

    bars: list
    rate: Optional[Dict[str, float]]
    state: str
    sources: List[Dict[str, Any]]


def accept(raw: Any, pinned_install_id: Optional[str]) -> Optional[PeerAnswer]:
    try:
        answer = PeerAnswer.model_validate(raw)
    except ValidationError as exc:
        logger.info("stats_feed_peer_bad_shape", errors=len(exc.errors()))
        return None
    if answer.v != WIRE_VERSION or not pinned_install_id or answer.install_id != pinned_install_id:
        logger.info("stats_feed_peer_refused", version_ok=answer.v == WIRE_VERSION, pinned=bool(pinned_install_id))
        return None
    return answer


def _failure(reason: str) -> Tuple[PeerWord, str]:
    """The word for a peer that did not answer. Example: _failure("http_404") -> ("not_supported", "http_404")."""
    if reason == "http_404":
        return "not_supported", reason
    if reason in ("disconnected", "timeout", "unreachable"):
        return "unreachable", reason
    return "refused", reason or "refused"


def _pinned(open_db: Any) -> Dict[str, peer_hosts.PeerRow]:
    with closing(open_db()) as conn:
        return {p.key: p for p in peer_hosts.list_peers(conn)}


async def pull_once(feed: "StatsFeed") -> bool:
    from src.api import peer_auth

    book, before = feed.peer_book, feed.peer_book.signature()
    book.asked_mono = feed._clock()
    try:
        pinned = await asyncio.to_thread(_pinned, peer_auth.open_db)
    except (sqlite3.Error, OSError, DatastoreUnreadableError) as exc:
        logger.warning("stats_feed_peers_unreadable", error_type=type(exc).__name__)
        for item in book.items.values():
            item.state, item.reason = "unreachable", "local_unreadable"
        return book.signature() != before
    sent = feed._wall()
    answers = await peer_fanout.ask_peers(PATH, peer_auth.open_db) if pinned else []
    rtt = max(feed._wall() - sent, 0.0)
    mono = feed._clock()
    for reply in answers:
        item = book.items.setdefault(reply.host_key, Imported(reply.host_key, reply.label))
        item.label = reply.label
        row = pinned.get(reply.host_key)
        answer = accept(reply.data, row.peer_install_id if row else None) if reply.data is not None else None
        if answer is None:
            item.state, item.reason = _failure(reply.reason if reply.data is None else "bad_answer")
            if item.good_mono is not None and mono - item.good_mono > STALE_S:
                item.answer = None
            continue
        observed = answer.now - (sent + rtt / 2)
        item.skew = observed if item.skew is None else SKEW_ALPHA * observed + (1 - SKEW_ALPHA) * item.skew
        item.answer, item.good_mono, item.good_wall = answer, mono, feed._wall()
        item.state, item.reason = answer.state, ""
    asked = {r.host_key for r in answers}
    for key in set(book.items) - set(pinned) - asked:
        del book.items[key]
    for key, row in pinned.items():
        if key not in asked:
            item = book.items.setdefault(key, Imported(key, row.label))
            item.label, item.state, item.reason = row.label, "unreachable", "not_asked"
    return book.signature() != before


async def pull(feed: "StatsFeed", *, pulled: bool = False) -> None:
    if pulled:
        await feed._sleep(PULL_S)
    while feed.owner_leased():
        if await pull_once(feed):
            feed.peers_changed()
        await feed._sleep(PULL_S)


def effective(item: Imported, mono: float) -> Tuple[PeerWord, str]:
    if item.state not in FAILED and item.good_mono is not None and mono - item.good_mono > FRESH_S:
        return "unreachable", "stale"
    return item.state, item.reason


def _counted(item: Imported, mono: float) -> Optional[Tuple[Optional[float], Optional[RateWire]]]:
    answer = item.answer
    if answer is None or answer.windows is None or item.good_mono is None:
        return None
    failed = effective(item, mono)[0] in FAILED
    if failed and mono - item.good_mono > STALE_S:
        return None
    if answer.state in OWN_WORDS:
        return (answer.now if failed else None), (None if failed else answer.rate)
    return (answer.data_through or 0.0), None


def _bars(answer: PeerAnswer, spec: WindowSpec, now: float, through: Optional[float]) -> list:
    last = int(now // spec.bucket_s) * spec.bucket_s
    rows: Dict[int, Classes] = {}
    for t, fresh, write, read, out in (answer.windows or {}).get(spec.name, []):
        start = min(t - t % spec.bucket_s, last)
        rows[start] = rows.get(start, Classes()).plus(Classes(fresh, write, read, out))
    return fold(spec, now, rows, rows, answer.gaps, through)


def _totals(bars: Sequence[Optional[Classes]]) -> Optional[Dict[str, int]]:
    counted = [b for b in bars if b is not None]
    if not counted:
        return None
    total = Classes(*(sum(part) for part in zip(*counted)))
    return {"fresh": total.fresh, "cache_write": total.cache_write, "cache_read": total.cache_read, "out": total.out}


def overlay(book: PeerBook, spec: WindowSpec, now: float, mono: float, own_bars: list,
            own_rate: Optional[Dict[str, float]], own_word: str) -> Merged:
    bars, rates, sources, any_down = list(own_bars), [own_rate] if own_rate else [], [], False
    for item in sorted(book.items.values(), key=lambda i: i.label):
        counted = _counted(item, mono)
        peer_bars = _bars(item.answer, spec, now, counted[0]) if counted and item.answer else None
        if peer_bars is not None:
            bars = merge(bars, [peer_bars])
            if counted and counted[1] is not None:
                rates.append({**counted[1].model_dump()})
        answer = item.answer
        word, reason = effective(item, mono)
        sources.append({
            "host_key": item.key, "label": item.label, "state": word, **({"reason": reason} if reason else {}),
            "data_through": (counted[0] if counted and counted[0] is not None else answer.data_through) if answer else None,
            "as_of": item.good_wall, "skew_seconds": None if item.skew is None else round(item.skew, 1),
            "skewed": item.skew is not None and abs(item.skew) > SKEW_FLAG_S,
            "totals": _totals(peer_bars) if peer_bars is not None else None})
        any_down = any_down or word != "ok"
    rate = None
    if rates:
        rate = {k: round(sum(r[k] for r in rates), 1) for k in ("fresh", "cache_write", "cache_read", "out")}
        rate["span_seconds"] = max(r["span_seconds"] for r in rates)
    state = own_word if own_word not in OWN_WORDS else ("partial" if any_down else own_word)
    return Merged(bars, rate, state, sources)
