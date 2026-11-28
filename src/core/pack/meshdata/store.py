
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Collection, Dict, FrozenSet, List, NamedTuple, Optional, Sequence, Set, Tuple

import structlog

from src.core.computers import direction
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.machines.settings_sign import Signing, signature_from
from src.core.pack.meshdata import envelope, hlc
from src.core.pack.meshdata import withhold
from src.core.pack.meshdata.kinds import KINDS, MAX_KEY_LEN, KindRule, MAX_VALUE_BYTES

log = structlog.get_logger(__name__)

FILENAME = "pack-meshdata.db"
FLOOR_CAP_FACTOR = 4
_EQUIVOCATION_MEMORY = 256
_VIEW_MEMO = 8
_ENTRY_CACHE_MAX = 40_000
_MAX_REASSERT = 32

DDL: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS records (
        kind TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, ms INTEGER NOT NULL, ctr INTEGER NOT NULL,
        origin TEXT NOT NULL, h TEXT NOT NULL, sig_json TEXT NOT NULL, kid TEXT NOT NULL, direct INTEGER NOT NULL DEFAULT 0,
        received_ms INTEGER NOT NULL, PRIMARY KEY (kind, key))""",
    "CREATE TABLE IF NOT EXISTS floors (kind TEXT NOT NULL, key TEXT NOT NULL, ms INTEGER NOT NULL, ctr INTEGER NOT NULL, iid TEXT NOT NULL, tomb INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (kind, key))",
    "CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS records_kind_origin ON records(kind, origin)",
)


class Outcome(NamedTuple):

    accepted: int
    same: int
    stale: int
    refused: int
    bad_origins: Set[str]


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _name(kind: str, key: str) -> str:
    return f"{kind}:{key}"


class RecordStore:

    def __init__(self, path: Path, own_iid: str, wall: Callable[[], int] = hlc.wall_ms, signing: Optional[Signing] = None) -> None:
        self.path = Path(path)
        self.signing = signing
        self.own_iid = own_iid
        self._wall = wall
        self._lock = threading.Lock()
        self._equivocations: Set[Tuple[str, str, str, int, int]] = set()
        self._writes = 0
        self.generation = 0
        self._withheld_memo: Tuple[Optional[tuple], Dict[str, FrozenSet[str]]] = (None, {})
        self._views: "OrderedDict[tuple, Tuple[Dict[str, Dict[str, Any]], str]]" = OrderedDict()
        self._entries: Dict[Tuple[str, str], Tuple[tuple, Dict[str, Any]]] = {}
        self._reconciled: Optional[tuple] = None
        self._pruned: Optional[tuple] = None
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600))
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            for statement in DDL:
                conn.execute(statement)
            if "tomb" not in [r[1] for r in conn.execute("PRAGMA table_info(floors)").fetchall()]:
                conn.execute("ALTER TABLE floors ADD COLUMN tomb INTEGER NOT NULL DEFAULT 0")
            conn.execute("INSERT OR IGNORE INTO meta (name, value) VALUES ('store_id', ?)", (secrets.token_hex(16),))
        self._clock = self._seed_clock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _seed_clock(self) -> hlc.Clock:
        with closing(self._connect()) as conn:
            saved = conn.execute("SELECT value FROM meta WHERE name = 'clock'").fetchone()
            own = conn.execute("SELECT ms, ctr FROM records WHERE origin = ? ORDER BY ms DESC, ctr DESC LIMIT 1", (self.own_iid,)).fetchone()
        last = None
        if saved:
            try:
                last = hlc.parse_stamp(json.loads(saved[0]))
            except ValueError:
                last = None
        if own and (last is None or hlc.Stamp(own[0], own[1], self.own_iid) > last):
            last = hlc.Stamp(own[0], own[1], self.own_iid)
        return hlc.Clock(self.own_iid, last, self._wall)

    def store_id(self) -> str:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT value FROM meta WHERE name = 'store_id'").fetchone()[0]

    @staticmethod
    def _room_ok(rule: Any, lst: Any, origin: str, kind_n: int, origin_n: int, member: bool = False) -> bool:
        priv = rule.privileged is not None and rule.privileged(lst, origin)
        if kind_n >= rule.cap:
            return False
        if not (priv and not member) and kind_n >= max(0, rule.cap - rule.reserve):
            return False
        return priv or rule.origin_cap is None or origin_n < rule.origin_cap

    @staticmethod
    def _withholders(conn: sqlite3.Connection, lst: Any, peer: str) -> Set[str]:
        kids = {c.install_id: envelope.kid(c.fed_public_key) for c in lst.computers}
        out: Set[str] = set()
        for text, origin, kid in conn.execute("SELECT value_json, origin, kid FROM records WHERE kind = ?", (withhold.KIND,)).fetchall():
            value = json.loads(text)
            if kids.get(origin) == kid and withhold.valid(value) and peer in value["ids"]:
                out.add(origin)
        return out

    def clock(self) -> hlc.Clock:
        return self._clock

    def _save_clock(self, conn: sqlite3.Connection) -> None:
        last = self._clock.last
        if last is not None:
            conn.execute("INSERT OR REPLACE INTO meta (name, value) VALUES ('clock', ?)", (json.dumps(last.wire()),))

    def _note_equivocation(self, origin: str, kind: str, key: str, stamp: hlc.Stamp) -> None:
        mark = (origin, kind, key, stamp.ms, stamp.ctr)
        if mark in self._equivocations:
            return
        if len(self._equivocations) >= _EQUIVOCATION_MEMORY:
            self._equivocations.clear()
        self._equivocations.add(mark)
        log.warning("meshdata_equivocation", origin=origin, kind=kind)

    @staticmethod
    def _parse(name: Any, entry: Any) -> Optional[Tuple[str, str, hlc.Stamp, Any, Any]]:
        if not isinstance(name, str) or ":" not in name or not isinstance(entry, dict):
            return None
        kind, key = name.split(":", 1)
        rule = KINDS.get(kind)
        stamp = hlc.parse_stamp(entry.get("s"))
        sig = signature_from(entry.get("sig"))
        if rule is None or not 1 <= len(key) <= MAX_KEY_LEN or stamp is None or sig is None or sig.signer != stamp.iid:
            return None
        if rule.key_is_origin and key != stamp.iid:
            return None
        value = entry.get("v")
        try:
            if len(canonical(value)) > MAX_VALUE_BYTES or not rule.validate(value) or (rule.key_ok is not None and not rule.key_ok(key, value)):
                return None
        except (ValueError, TypeError, RecursionError):
            return None
        return kind, key, stamp, value, sig

    def offer_batch(self, entries: Any, from_peer: str, lst: Any, now_ms: int, gen: Optional[int] = None) -> Outcome:
        accepted = same = stale = refused = 0
        bad: Set[str] = set()
        reassert: List[Tuple[str, str]] = []
        if not isinstance(entries, dict) or not isinstance(lst, RosterV2):
            return Outcome(0, 0, 0, len(entries) if isinstance(entries, dict) else 0, bad)
        with self._lock, closing(self._connect()) as conn:
            if gen is not None and gen != self.generation:
                return Outcome(0, 0, 0, 0, bad)
            conn.execute("BEGIN IMMEDIATE")
            try:
                kind_n = dict(conn.execute("SELECT kind, COUNT(*) FROM records GROUP BY kind").fetchall()) if entries else {}
                origin_n = {(k, o): n for k, o, n in conn.execute("SELECT kind, origin, COUNT(*) FROM records GROUP BY kind, origin").fetchall()} if entries else {}
                withheld = self._withholders(conn, lst, self.own_iid) if entries else set()
                for name, entry in entries.items():
                    parsed = self._parse(name, entry)
                    if parsed is None:
                        refused += 1
                        continue
                    kind, key, stamp, value, sig = parsed
                    origin = stamp.iid
                    listed = lst.entry(origin)
                    rule = KINDS[kind]
                    if (origin in bad or listed is None or hlc.too_far_ahead(stamp, now_ms) or (rule.origin_ok is not None and not rule.origin_ok(lst, origin))
                            or not self._may(rule, lst, self.own_iid)
                            or (origin in withheld and kind != withhold.KIND)
                            or (rule.tomb is not None and rule.tomb(value) and stamp.ms + rule.tomb_ttl_ms < now_ms)):
                        refused += 1
                        continue
                    h = envelope.body_hash(value)
                    verdict, old_origin = self._admit(conn, kind, key, stamp, h, kid=envelope.kid(listed.fed_public_key), from_peer=from_peer,
                                                      kind_n=kind_n, origin_n=origin_n, lst=lst, live=rule.tomb is None or not rule.tomb(value))
                    if verdict == "same":
                        same += 1
                        continue
                    if verdict == "stale_floor":
                        if not envelope.verify(envelope.KIND_RECORD, origin, _name(kind, key), stamp.wire(), h, sig, lst):
                            bad.add(origin)
                            refused += 1
                            continue
                        stale += 1
                        if len(reassert) < _MAX_REASSERT:
                            reassert.append((kind, key))
                            kind_n[kind] = kind_n.get(kind, 0) + 1
                        continue
                    if verdict not in ("new", "equivocation"):
                        stale += verdict == "stale"
                        refused += verdict == "refused"
                        continue
                    if not envelope.verify(envelope.KIND_RECORD, origin, _name(kind, key), stamp.wire(), h, sig, lst):
                        bad.add(origin)
                        refused += 1
                        continue
                    conn.execute("INSERT OR REPLACE INTO records (kind, key, value_json, ms, ctr, origin, h, sig_json, kid, direct, received_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (kind, key, canonical(value), stamp.ms, stamp.ctr, origin, h, json.dumps(sig.to_dict()), envelope.kid(listed.fed_public_key),
                                  int(origin == from_peer), now_ms))
                    if verdict == "equivocation":
                        self._note_equivocation(origin, kind, key, stamp)
                    if old_origin is None:
                        kind_n[kind] = kind_n.get(kind, 0) + 1
                    else:
                        origin_n[(kind, old_origin)] = origin_n.get((kind, old_origin), 1) - 1
                    origin_n[(kind, origin)] = origin_n.get((kind, origin), 0) + 1
                    self._clock.see(stamp)
                    accepted += 1
                if accepted:
                    self._save_clock(conn)
                conn.execute("COMMIT")
                self._writes += bool(accepted)
                if accepted and self._pruned is not None and self._pruned[0] != self.fingerprint(lst):
                    self._pruned = None
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        self._reassert(reassert, lst, gen)
        return Outcome(accepted, same, stale, refused, bad)

    def _reassert(self, keys: List[Tuple[str, str]], lst: Any, gen: Optional[int] = None) -> None:
        done = 0
        for kind, key in keys:
            rule = KINDS[kind]
            if self.signing is not None and rule.tomb_value is not None and (rule.origin_ok is None or rule.origin_ok(lst, self.own_iid)):
                done += self.put_own(kind, key, rule.tomb_value, self.signing, lst=lst, member_room=True, gen=gen)
        if done:
            log.info("meshdata_reasserted", kind=keys[0][0], count=done)

    def _admit(self, conn: sqlite3.Connection, kind: str, key: str, stamp: hlc.Stamp, h: str, *, kid: str, from_peer: str,
               kind_n: Dict[str, int], origin_n: Dict[Tuple[str, str], int], lst: Any, live: bool = True) -> Tuple[str, Optional[str]]:
        row = conn.execute("SELECT ms, ctr, origin, h, kid, direct FROM records WHERE kind = ? AND key = ?", (kind, key)).fetchone()
        floor_row = conn.execute("SELECT ms, ctr, iid, tomb FROM floors WHERE kind = ? AND key = ?", (kind, key)).fetchone()
        floor = hlc.Stamp(*floor_row[:3]) if floor_row else None
        if row is not None and row[4] == kid:
            held = hlc.Stamp(row[0], row[1], row[2])
            if (stamp, h) < (held, row[3]):
                return "stale", None
            if (stamp, h) == (held, row[3]):
                if stamp.iid == from_peer and not row[5]:
                    conn.execute("UPDATE records SET direct = 1 WHERE kind = ? AND key = ?", (kind, key))
                return "same", None
            return ("equivocation" if stamp == held else "new"), row[2]
        if row is not None:
            held = hlc.Stamp(row[0], row[1], row[2])
            floor = max(floor, held) if floor is not None else held
        else:
            rule = KINDS[kind]
            if not self._room_ok(rule, lst, stamp.iid, kind_n.get(kind, 0), origin_n.get((kind, stamp.iid), 0)):
                return "refused", None
        if floor is not None and stamp < floor:
            rule = KINDS[kind]
            if row is None and floor_row[3] and live and rule.tomb_value is not None:
                if kind_n.get(kind, 0) >= max(0, rule.cap - rule.reserve):
                    return "stale", None
                return "stale_floor", None
            return "stale", None
        return "new", (row[2] if row is not None else None)

    def _drop(self, conn: sqlite3.Connection, kind: str, key: str, tomb: bool = False) -> None:
        row = conn.execute("SELECT ms, ctr, origin FROM records WHERE kind = ? AND key = ?", (kind, key)).fetchone()
        if row is None:
            return
        floor_row = conn.execute("SELECT ms, ctr, iid FROM floors WHERE kind = ? AND key = ?", (kind, key)).fetchone()
        top = max(hlc.Stamp(*row), hlc.Stamp(*floor_row)) if floor_row else hlc.Stamp(*row)
        conn.execute("INSERT OR REPLACE INTO floors (kind, key, ms, ctr, iid, tomb) VALUES (?,?,?,?,?,?)", (kind, key, top.ms, top.ctr, top.iid, int(tomb)))
        conn.execute("DELETE FROM records WHERE kind = ? AND key = ?", (kind, key))

    def _may(self, rule: KindRule, lst: Any, peer: Optional[str]) -> bool:
        return ((rule.serve_ok is None or bool(rule.serve_ok(lst, peer))) and (rule.local_ok is None or bool(rule.local_ok(self.own_iid, peer))))

    @staticmethod
    def _forget(conn: sqlite3.Connection, kind: str, key: str) -> None:
        conn.execute("DELETE FROM records WHERE kind = ? AND key = ?", (kind, key))

    def drop(self, kind: str, key: str) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._drop(conn, kind, key)
                conn.execute("COMMIT")
                self._writes += 1
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def reconcile(self, lst: Any, signing: Optional[Signing] = None, gen: Optional[int] = None) -> None:
        if not isinstance(lst, RosterV2):
            return
        fingerprint = self.fingerprint(lst)
        if fingerprint == self._reconciled:
            return
        signing = signing or self.signing
        own_kid = envelope.own_kid(signing) if signing is not None else None
        with self._lock, closing(self._connect()) as conn:
            if gen is not None and gen != self.generation:
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                for kind, key, origin, row_kid, ms, ctr, h in conn.execute("SELECT kind, key, origin, kid, ms, ctr, h FROM records").fetchall():
                    listed = lst.entry(origin)
                    if listed is None:
                        self._drop(conn, kind, key)
                        continue
                    listed_kid = envelope.kid(listed.fed_public_key)
                    if row_kid == listed_kid:
                        continue
                    if origin != self.own_iid:
                        self._drop(conn, kind, key)
                    elif own_kid is not None and own_kid == listed_kid:
                        sig = envelope.try_sign(envelope.KIND_RECORD, _name(kind, key), [ms, ctr, origin], h, signing)
                        if sig is not None:
                            conn.execute("UPDATE records SET sig_json = ?, kid = ? WHERE kind = ? AND key = ?", (json.dumps(sig.to_dict()), listed_kid, kind, key))
                self._trim_floors(conn, lst)
                conn.execute("COMMIT")
                self._writes += 1
                self._reconciled = fingerprint
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _trim_floors(conn: sqlite3.Connection, lst: RosterV2) -> None:
        for kind, rule in KINDS.items():
            gone = [r for r in conn.execute("SELECT key, ms, ctr, iid FROM floors WHERE kind = ? ORDER BY ms, ctr, iid", (kind,)).fetchall() if lst.entry(r[3]) is None]
            for key, *_ in gone[:max(0, len(gone) - FLOOR_CAP_FACTOR * rule.cap)]:
                conn.execute("DELETE FROM floors WHERE kind = ? AND key = ?", (kind, key))

    @staticmethod
    def _trim_tomb_floors(conn: sqlite3.Connection) -> None:
        for kind, rule in KINDS.items():
            if rule.tomb is None:
                continue
            extra = conn.execute("SELECT COUNT(*) FROM floors WHERE kind = ?", (kind,)).fetchone()[0] - FLOOR_CAP_FACTOR * rule.cap
            if extra > 0:
                conn.execute("DELETE FROM floors WHERE kind = ? AND key IN (SELECT key FROM floors WHERE kind = ? ORDER BY ms, ctr, iid LIMIT ?)", (kind, kind, extra))

    def gc(self, now_ms: int) -> int:
        dropped = 0
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for kind, rule in KINDS.items():
                    if rule.tomb is None:
                        continue
                    for key, text, ms in conn.execute("SELECT key, value_json, ms FROM records WHERE kind = ? AND value_json LIKE '%null%' ORDER BY ms", (kind,)).fetchall():
                        if now_ms - ms > rule.tomb_ttl_ms and rule.tomb(json.loads(text)):
                            self._drop(conn, kind, key, tomb=True)
                            dropped += 1
                self._trim_tomb_floors(conn)
                conn.execute("COMMIT")
                self._writes += bool(dropped)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return dropped

    def prune(self, lst: Any, gen: Optional[int] = None) -> int:
        if not isinstance(lst, RosterV2):
            return 0
        writes_then = self._writes
        fingerprint = self.fingerprint(lst)
        forget: Set[Tuple[str, str, str]] = set()
        drop: Set[Tuple[str, str, str]] = set()
        with closing(self._connect()) as conn:
            sig = tuple(sorted(conn.execute("SELECT origin, h FROM records WHERE kind = ?", (withhold.KIND,)).fetchall()))
            holds = tuple(self._may(rule, lst, self.own_iid) for rule in KINDS.values())
            list_ok = {k: rule.serve_ok is None or bool(rule.serve_ok(lst, self.own_iid)) for k, rule in KINDS.items()}
            drop_local = {k: rule.local_ok is not None and not rule.local_ok(self.own_iid, self.own_iid)
                          and (rule.forget_ok is None or bool(rule.forget_ok(self.own_iid))) for k, rule in KINDS.items()}
            memo = (fingerprint, sig, holds, tuple(drop_local.values()))
            if self._pruned == memo:
                return 0
            withheld = self._withholders(conn, lst, self.own_iid)
            answers: Dict[Tuple[str, str], bool] = {}
            for kind, key, origin in conn.execute("SELECT kind, key, origin FROM records").fetchall():
                rule = KINDS[kind] if kind in KINDS else None
                if rule is None:
                    continue
                if not list_ok[kind] or drop_local[kind]:
                    forget.add((kind, key, origin))
                    continue
                if rule.origin_ok is not None and lst.entry(origin) is not None:
                    ok = answers.setdefault((kind, origin), bool(rule.origin_ok(lst, origin)))
                    if not ok:
                        forget.add((kind, key, origin))
                        continue
                if origin in withheld and kind != withhold.KIND:
                    drop.add((kind, key, origin))
        dropped = 0
        if forget or drop:
            with self._lock, closing(self._connect()) as conn:
                if gen is not None and gen != self.generation:
                    return 0
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for kind, key, origin in sorted(forget | drop):
                        if conn.execute("SELECT 1 FROM records WHERE kind = ? AND key = ? AND origin = ?", (kind, key, origin)).fetchone() is None:
                            continue
                        if (kind, key, origin) in forget:
                            self._forget(conn, kind, key)
                        else:
                            self._drop(conn, kind, key)
                        dropped += 1
                    conn.execute("COMMIT")
                    self._writes += bool(dropped)
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
        with self._lock:
            if self._writes == writes_then + bool(dropped):
                self._pruned = memo
        return dropped

    def clear(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM records")
                conn.execute("DELETE FROM floors")
                conn.execute("UPDATE meta SET value = ? WHERE name = 'store_id'", (secrets.token_hex(16),))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            self._writes += 1
            self.generation += 1
            self._withheld_memo = (None, {})
            self._views.clear()
            self._entries.clear()
            self._reconciled = None
            self._pruned = None
            self._equivocations.clear()

    def _own_allowed(self, kind: str, rule: Any, lst: Any) -> bool:
        if isinstance(lst, RosterV2) and (rule.origin_ok is None or rule.origin_ok(lst, self.own_iid)):
            return True
        log.info("meshdata_own_refused", kind=kind, reason="origin")
        return False

    def put_own(self, kind: str, key: str, value: Any, signing: Signing, force: bool = False, lst: Any = None, member_room: bool = False, gen: Optional[int] = None) -> bool:
        rule = KINDS.get(kind)
        if rule is None or not rule.validate(value) or (rule.key_is_origin and key != self.own_iid) or (rule.key_ok is not None and not rule.key_ok(key, value)):
            return False
        if lst is not None and not self._own_allowed(kind, rule, lst):
            return False
        text = canonical(value)
        own_kid = envelope.own_kid(signing)
        if len(text) > MAX_VALUE_BYTES or own_kid is None:
            return False
        with self._lock, closing(self._connect()) as conn:
            if gen is not None and gen != self.generation:
                return False
            held = conn.execute("SELECT value_json, origin, ms, ctr FROM records WHERE kind = ? AND key = ?", (kind, key)).fetchone()
            if held is not None and held[0] == text and held[1] == self.own_iid and not force:
                return False
            if held is None and lst is not None:
                counts = (conn.execute("SELECT COUNT(*) FROM records WHERE kind = ?", (kind,)).fetchone()[0],
                          conn.execute("SELECT COUNT(*) FROM records WHERE kind = ? AND origin = ?", (kind, self.own_iid)).fetchone()[0])
                if not self._room_ok(rule, lst, self.own_iid, *counts, member=member_room):
                    log.info("meshdata_own_refused", kind=kind, reason="room")
                    return False
            floor_row = conn.execute("SELECT ms, ctr, iid FROM floors WHERE kind = ? AND key = ?", (kind, key)).fetchone()
            tops = ([hlc.Stamp(held[2], held[3], held[1])] if held is not None else []) + ([hlc.Stamp(*floor_row)] if floor_row else [])
            stamp = self._clock.now()
            if tops and stamp <= max(tops):
                stamp = self._clock.after(max(tops))
            h = envelope.body_hash(value)
            sig = envelope.try_sign(envelope.KIND_RECORD, _name(kind, key), stamp.wire(), h, signing)
            if sig is None:
                return False
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("INSERT OR REPLACE INTO records (kind, key, value_json, ms, ctr, origin, h, sig_json, kid, direct, received_ms) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                             (kind, key, text, stamp.ms, stamp.ctr, self.own_iid, h, json.dumps(sig.to_dict()), own_kid, self._wall()))
                self._save_clock(conn)
                conn.execute("COMMIT")
                self._writes += 1
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return True

    def put_many(self, kind: str, items: Sequence[Tuple[str, Any, Optional[hlc.Stamp]]], signing: Signing, lst: Any,
                 member_keys: Collection[str] = frozenset(), gen: Optional[int] = None) -> Tuple[int, int]:
        rule, own_kid = KINDS.get(kind), envelope.own_kid(signing)
        if rule is None or own_kid is None or not self._own_allowed(kind, rule, lst):
            return 0, 0
        written = refused = 0
        with self._lock, closing(self._connect()) as conn:
            if gen is not None and gen != self.generation:
                return 0, 0
            conn.execute("BEGIN IMMEDIATE")
            try:
                kind_n = conn.execute("SELECT COUNT(*) FROM records WHERE kind = ?", (kind,)).fetchone()[0]
                origin_n = {o: n for o, n in conn.execute("SELECT origin, COUNT(*) FROM records WHERE kind = ? GROUP BY origin", (kind,)).fetchall()}
                for key, value, given in items:
                    if (not isinstance(key, str) or not 1 <= len(key) <= MAX_KEY_LEN or not rule.validate(value) or (rule.key_is_origin and key != self.own_iid)
                            or (rule.key_ok is not None and not rule.key_ok(key, value)) or (given is not None and given.iid != self.own_iid)):
                        continue
                    text = canonical(value)
                    if len(text) > MAX_VALUE_BYTES:
                        continue
                    held = conn.execute("SELECT value_json, origin, ms, ctr FROM records WHERE kind = ? AND key = ?", (kind, key)).fetchone()
                    floor_row = conn.execute("SELECT ms, ctr, iid FROM floors WHERE kind = ? AND key = ?", (kind, key)).fetchone()
                    held_stamp = hlc.Stamp(held[2], held[3], held[1]) if held is not None else None
                    floor = hlc.Stamp(*floor_row) if floor_row else None
                    if given is None:
                        if held is not None and held[0] == text and held[1] == self.own_iid:
                            continue
                        stamp = self._clock.now()
                        tops = [t for t in (held_stamp, floor) if t is not None]
                        if tops and stamp <= max(tops):
                            stamp = self._clock.after(max(tops))
                    else:
                        if (held_stamp is not None and given <= held_stamp) or (floor is not None and given < floor):
                            continue
                        stamp = given
                    if held is None and not self._room_ok(rule, lst, self.own_iid, kind_n, origin_n.get(self.own_iid, 0), member=key in member_keys):
                        refused += 1
                        continue
                    h = envelope.body_hash(value)
                    sig = envelope.try_sign(envelope.KIND_RECORD, _name(kind, key), stamp.wire(), h, signing)
                    if sig is None:
                        continue
                    conn.execute("INSERT OR REPLACE INTO records (kind, key, value_json, ms, ctr, origin, h, sig_json, kid, direct, received_ms) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                                 (kind, key, text, stamp.ms, stamp.ctr, self.own_iid, h, json.dumps(sig.to_dict()), own_kid, self._wall()))
                    if held is None:
                        kind_n += 1
                    else:
                        origin_n[held[1]] = origin_n.get(held[1], 1) - 1
                    origin_n[self.own_iid] = origin_n.get(self.own_iid, 0) + 1
                    if given is not None:
                        self._clock.see(stamp)
                    written += 1
                if written:
                    self._save_clock(conn)
                conn.execute("COMMIT")
                self._writes += bool(written)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        if refused:
            log.info("meshdata_own_refused", kind=kind, reason="room", count=refused)
        return written, refused

    def own_stamp_ms(self, kind: str, key: str) -> Optional[int]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT ms FROM records WHERE kind = ? AND key = ? AND origin = ?", (kind, key, self.own_iid)).fetchone()
        return row[0] if row else None

    @staticmethod
    def fingerprint(lst: Any) -> tuple:
        return (lst.generation, lst.alpha, lst.home, tuple(direction.one_way_ids()),
                tuple((c.install_id, envelope.kid(c.fed_public_key), c.one_way, c.may_receive_logins) for c in lst.computers))

    def _rows(self, lst: Any, kind: Optional[str] = None, light: bool = False) -> List[tuple]:
        if not isinstance(lst, RosterV2):
            return []
        heavy = "NULL, " if light else "value_json, "
        sql = f"SELECT kind, key, {heavy}ms, ctr, origin, {'NULL' if light else 'sig_json'}, kid, direct, received_ms, h FROM records"
        args: tuple = ()
        if kind is not None:
            sql, args = sql + " WHERE kind = ?", (kind,)
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, args).fetchall()
        kids = {c.install_id: envelope.kid(c.fed_public_key) for c in lst.computers}
        return [r for r in rows if kids.get(r[5]) == r[7]]

    def _entries_for(self, rows: List[tuple]) -> List[Optional[Dict[str, Any]]]:
        out: List[Optional[Dict[str, Any]]] = []
        misses: Dict[Tuple[str, str], int] = {}
        for index, row in enumerate(rows):
            mark = (row[3], row[4], row[5], row[7], row[10])
            cached = self._entries.get((row[0], row[1]))
            if cached is not None and cached[0] == mark:
                out.append(cached[1])
            else:
                out.append(None)
                misses[(row[0], row[1])] = index
        if misses:
            if len(self._entries) + len(misses) >= _ENTRY_CACHE_MAX:
                self._entries.clear()
            names = list(misses)
            with closing(self._connect()) as conn:
                for start in range(0, len(names), 400):
                    chunk = names[start:start + 400]
                    marks = ",".join("(?,?)" for _ in chunk)
                    for kind, key, value_json, sig_json, ms, ctr, origin, h in conn.execute(
                            f"SELECT kind, key, value_json, sig_json, ms, ctr, origin, h FROM records WHERE (kind, key) IN (VALUES {marks})", [x for name in chunk for x in name]).fetchall():
                        index = misses.get((kind, key))
                        row = rows[index] if index is not None else None
                        if row is None or (ms, ctr, origin, h) != (row[3], row[4], row[5], row[10]):
                            continue
                        entry = {"v": json.loads(value_json), "s": [row[3], row[4], row[5]], "sig": json.loads(sig_json)}
                        self._entries[(kind, key)] = ((row[3], row[4], row[5], row[7], row[10]), entry)
                        out[index] = entry
        return out

    def view(self, lst: Any, for_peer: Optional[str] = None) -> Tuple[Dict[str, Dict[str, Any]], str]:
        if not isinstance(lst, RosterV2):
            return {}, self.digest({})
        withheld: FrozenSet[str] = frozenset()
        serve: Dict[str, bool] = {}
        writes, fp = self._writes, self.fingerprint(lst)
        if for_peer is not None:
            withheld = self._withheld_for(lst, for_peer, writes, fp)
            serve = {kind: self._may(rule, lst, for_peer) for kind, rule in KINDS.items()}
            memo_key = (writes, fp, tuple(sorted(serve.items())), withheld)
        else:
            memo_key = (writes, fp, None)
        with self._lock:
            hit = self._views.get(memo_key)
            if hit is not None:
                self._views.move_to_end(memo_key)
                return hit
        rows = self._rows(lst, light=True)
        if for_peer is not None:
            rows = [r for r in rows if (r[0] == withhold.KIND or r[5] not in withheld) and serve.get(r[0], False)]
        kept = [(r, e) for r, e in zip(rows, self._entries_for(rows)) if e is not None]
        servable = {_name(r[0], r[1]): e for r, e in kept}
        digest = self._digest_rows([r for r, _e in kept])
        if len(kept) == len(rows):
            self._remember(memo_key, (servable, digest))
        return servable, digest

    def _withheld_for(self, lst: Any, peer: str, writes: int, fp: tuple) -> FrozenSet[str]:
        with self._lock:
            key, by_peer = self._withheld_memo
            if key == (writes, fp) and peer in by_peer:
                return by_peer[peer]
        with closing(self._connect()) as conn:
            found = frozenset(self._withholders(conn, lst, peer))
        with self._lock:
            if self._writes == writes:
                if self._withheld_memo[0] != (writes, fp):
                    self._withheld_memo = ((writes, fp), {})
                self._withheld_memo[1][peer] = found
        return found

    def withholding(self, lst: Any, peer: str) -> FrozenSet[str]:
        return self._withheld_for(lst, peer, self._writes, self.fingerprint(lst))

    def _remember(self, memo_key: tuple, value: tuple) -> None:
        with self._lock:
            self._views[memo_key] = value
            while len(self._views) > _VIEW_MEMO:
                self._views.popitem(last=False)

    def _kind_view(self, lst: Any, kind: str) -> Tuple[Dict[str, Tuple[Any, hlc.Stamp]], str]:
        if not isinstance(lst, RosterV2):
            return {}, self.digest({})
        memo_key = (self._writes, self.fingerprint(lst), ("kind", kind))
        with self._lock:
            hit = self._views.get(memo_key)
            if hit is not None:
                self._views.move_to_end(memo_key)
                return hit
        rows = self._rows(lst, kind)
        rule = KINDS.get(kind)
        if rule is not None and rule.origin_ok is not None:
            answers: Dict[str, bool] = {}
            rows = [r for r in rows if answers.setdefault(r[5], bool(rule.origin_ok(lst, r[5])) and not direction.contained(r[5]))]
        value = ({r[1]: (json.loads(r[2]), hlc.Stamp(r[3], r[4], r[5])) for r in rows}, self._digest_rows(rows))
        self._remember(memo_key, value)
        return value

    def kind_rows(self, lst: Any, kind: str) -> Dict[str, Tuple[Any, hlc.Stamp]]:
        return self._kind_view(lst, kind)[0]

    def kind_digest(self, lst: Any, kind: str) -> str:
        return self._kind_view(lst, kind)[1]

    def servable(self, lst: Any, for_peer: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        return self.view(lst, for_peer)[0]

    @staticmethod
    def _digest_of(lines: List[str]) -> str:
        return hashlib.sha256("\n".join(sorted(lines)).encode("ascii")).hexdigest()[:32]

    @staticmethod
    def _digest_rows(rows: List[tuple]) -> str:
        return RecordStore._digest_of([f"{_name(r[0], r[1])}\t{r[3]}\t{r[4]}\t{r[5]}\t{r[10]}" for r in rows])

    @staticmethod
    def digest(servable_map: Dict[str, Dict[str, Any]]) -> str:
        return RecordStore._digest_of([f"{name}\t{e['s'][0]}\t{e['s'][1]}\t{e['s'][2]}\t{envelope.body_hash(e['v'])}" for name, e in servable_map.items()])

    def heard(self, lst: Any, now_ms: int) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for _kind, _key, value, ms, _ctr, origin, _sig, _kid, direct, received, _h in self._rows(lst, "status"):
            if origin == self.own_iid:
                continue
            out[origin] = {"at_ms": ms, "age_s": max(0, now_ms - ms) // 1000, "received_ms": received, "via": "direct" if direct else "passed", **json.loads(value)}
        return out
