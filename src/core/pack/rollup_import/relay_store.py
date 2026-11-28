
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from src.core.federation import peer_hosts
from src.core.pack.machines import capabilities
from src.core.pack.rollup_import.ddl import (EPOCH_FLOOR_KEY, FLOOR_TABLE, META_TABLE, NAMES_FLOOR_KEY, OFFERS_TABLE, PROJECTS_TABLE,
                                             RELAY_REV_KEY, RELAY_STATE_TABLE, REV_TABLE, STATE_TABLE, delete_origin_rows, supplied_through)

MAX_NAME_CHARS = 200
MAX_ID_CHARS = 64
MAX_HOPS = 8
MAX_NAMES = 2000


def _next_rev(conn: sqlite3.Connection, step: int = 1) -> int:
    conn.execute(f"INSERT OR IGNORE INTO {META_TABLE} (k, v) VALUES (?, ?)", (RELAY_REV_KEY, int(time.time() * 1000)))
    conn.execute(f"UPDATE {META_TABLE} SET v = v + ? WHERE k = ?", (step, RELAY_REV_KEY))
    return int(conn.execute(f"SELECT v FROM {META_TABLE} WHERE k = ?", (RELAY_REV_KEY,)).fetchone()[0])


def stamp(conn: sqlite3.Connection, origin: str, conversation_id: str, hour: int, origin_rev: Optional[int] = None,
          sig: Optional[str] = None, epoch: Optional[int] = None) -> int:
    rev = _next_rev(conn)
    conn.execute(f"INSERT INTO {REV_TABLE} (peer_install_id, conversation_id, hour, rev, origin_rev, epoch, sig) VALUES (?, ?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT(peer_install_id, conversation_id, hour) DO UPDATE SET rev = excluded.rev, sig = excluded.sig, epoch = excluded.epoch, "
                 f"origin_rev = COALESCE(excluded.origin_rev, {REV_TABLE}.origin_rev)", (origin, conversation_id, hour, rev, origin_rev, epoch, sig))
    return rev


def _floor(conn: sqlite3.Connection, origin: str, key: str, hour: int) -> Optional[int]:
    row = conn.execute(f"SELECT floor FROM {FLOOR_TABLE} WHERE peer_install_id = ? AND conversation_id = ? AND hour = ?", (origin, key, hour)).fetchone()
    return None if row is None else int(row[0])


def _raise_floor(conn: sqlite3.Connection, origin: str, key: str, hour: int, value: int) -> None:
    conn.execute(f"INSERT INTO {FLOOR_TABLE} (peer_install_id, conversation_id, hour, floor) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(peer_install_id, conversation_id, hour) DO UPDATE SET floor = MAX(floor, excluded.floor)", (origin, key, hour, value))


def held_sig(conn: sqlite3.Connection, origin: str, conversation_id: str, hour: int) -> Optional[str]:
    row = conn.execute(f"SELECT sig FROM {REV_TABLE} WHERE peer_install_id = ? AND conversation_id = ? AND hour = ?", (origin, conversation_id, hour)).fetchone()
    return None if row is None else row[0]


def origin_rev(conn: sqlite3.Connection, origin: str, conversation_id: str, hour: int) -> int:
    held = _floor(conn, origin, conversation_id, hour)
    return -1 if held is None else held


def raise_origin_rev(conn: sqlite3.Connection, origin: str, conversation_id: str, hour: int, value: int) -> None:
    _raise_floor(conn, origin, conversation_id, hour, value)


def admit_epoch(conn: sqlite3.Connection, origin: str, epoch: int) -> bool:
    held = _floor(conn, origin, EPOCH_FLOOR_KEY, 0)
    if held is not None and epoch < held:
        return False
    if held is not None and epoch > held:
        delete_origin_rows(conn, origin)
        conn.execute(f"DELETE FROM {REV_TABLE} WHERE peer_install_id = ?", (origin,))
        _next_rev(conn)
    _raise_floor(conn, origin, EPOCH_FLOOR_KEY, 0, epoch)
    return True


SCOPE_EPOCH_KEY = "scope_epoch"
SCOPE_TAG_KEY = "scope_epoch_tag"


def scope_epoch(conn: sqlite3.Connection, digest: str) -> int:
    tag = int(hashlib.sha256(digest.encode()).hexdigest()[:15], 16)
    held = conn.execute(f"SELECT v FROM {META_TABLE} WHERE k = ?", (SCOPE_TAG_KEY,)).fetchone()
    if held is None:
        conn.execute(f"INSERT OR IGNORE INTO {META_TABLE} (k, v) VALUES (?, ?)", (SCOPE_EPOCH_KEY, int(time.time() * 1000)))
        conn.execute(f"INSERT INTO {META_TABLE} (k, v) VALUES (?, ?)", (SCOPE_TAG_KEY, tag))
    elif int(held[0]) != tag:
        conn.execute(f"UPDATE {META_TABLE} SET v = v + 1 WHERE k = ?", (SCOPE_EPOCH_KEY,))
        conn.execute(f"UPDATE {META_TABLE} SET v = ? WHERE k = ?", (tag, SCOPE_TAG_KEY))
    return int(conn.execute(f"SELECT v FROM {META_TABLE} WHERE k = ?", (SCOPE_EPOCH_KEY,)).fetchone()[0])


def restamp_origin(conn: sqlite3.Connection, origin: str) -> None:
    if conn.execute(f"SELECT 1 FROM {REV_TABLE} WHERE peer_install_id = ? LIMIT 1", (origin,)).fetchone() is None:
        return
    conn.execute(f"UPDATE {REV_TABLE} SET rev = ?, sig = NULL WHERE peer_install_id = ?", (_next_rev(conn), origin))


def current_rev(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(f"SELECT v FROM {META_TABLE} WHERE k = ?", (RELAY_REV_KEY,)).fetchone()
    return None if row is None else int(row[0])


def id_list(raw: Any) -> List[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [v for v in raw if isinstance(v, str) and 0 < len(v) <= MAX_ID_CHARS][:64] if isinstance(raw, list) else []


def _short_text(value: Any, limit: int) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() and len(value) <= limit else None


def clean_names(names: Any, homes: Any) -> Tuple[Dict[str, str], Dict[str, str]]:
    homes = homes if isinstance(homes, dict) else {}
    kept: Dict[str, str] = {}
    hints: Dict[str, str] = {}
    for key, name in (names.items() if isinstance(names, dict) else []):
        if len(kept) >= MAX_NAMES:
            break
        key, label = _short_text(key, MAX_ID_CHARS), _short_text(name, MAX_NAME_CHARS)
        if not key or not label or "/" in label or "\\" in label:
            continue
        kept[key] = label
        home = _short_text(homes.get(key), MAX_ID_CHARS)
        if home:
            hints[key] = home
    return kept, hints


def delete_origin_names(conn: sqlite3.Connection, origin: str) -> None:
    conn.execute(f"DELETE FROM {PROJECTS_TABLE} WHERE peer_install_id = ?", (origin,))
    conn.execute(f"UPDATE {STATE_TABLE} SET names_rev = NULL, names_sig = NULL, names_epoch = NULL WHERE peer_install_id = ?", (origin,))


def replace_names(conn: sqlite3.Connection, origin: str, names: Any, homes: Any) -> int:
    delete_origin_names(conn, origin)
    kept, hints = clean_names(names, homes)
    conn.executemany(f"INSERT OR REPLACE INTO {PROJECTS_TABLE} (peer_install_id, project, name, home_install_id) VALUES (?, ?, ?, ?)",
                     [(origin, key, label, hints.get(key)) for key, label in kept.items()])
    return len(kept)


def replace_names_signed(conn: sqlite3.Connection, origin: str, names: Any, homes: Any, rev: int, sig: str, epoch: int) -> bool:
    if conn.execute(f"SELECT 1 FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone() is None or not admit_epoch(conn, origin, epoch):
        return False
    if rev < origin_rev(conn, origin, NAMES_FLOOR_KEY, 0):
        return False
    replace_names(conn, origin, names, homes)
    conn.execute(f"UPDATE {STATE_TABLE} SET names_rev = ?, names_sig = ?, names_epoch = ? WHERE peer_install_id = ?", (rev, sig, epoch, origin))
    _raise_floor(conn, origin, NAMES_FLOOR_KEY, 0, rev)
    return True


def names_proof(conn: sqlite3.Connection, origin: str) -> Optional[Tuple[int, str, int]]:
    row = conn.execute(f"SELECT names_rev, names_sig, names_epoch FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()
    return None if row is None or row[0] is None or not row[1] or row[2] is None else (int(row[0]), str(row[1]), int(row[2]))


def record_offers(conn: sqlite3.Connection, forwarder: str, offers: Dict[str, int], now: float) -> None:
    conn.execute(f"DELETE FROM {OFFERS_TABLE} WHERE forwarder_install_id = ?", (forwarder,))
    conn.executemany(f"INSERT OR REPLACE INTO {OFFERS_TABLE} (forwarder_install_id, origin_install_id, hops, updated_at) VALUES (?, ?, ?, ?)",
                     [(forwarder, origin, hops, now) for origin, hops in offers.items()])


def held_supplier(conn: sqlite3.Connection, origin: str) -> Optional[Tuple[str, int]]:
    row = conn.execute(f"SELECT via, revision FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()
    return None if row is None else (str(row[0]), int(row[1]))


def supplier_ok(conn: sqlite3.Connection, install_id: str, members: FrozenSet[str] = frozenset()) -> bool:
    return paired(conn, install_id) or (capabilities.mesh_on() and install_id in members)


def choose_supplier(conn: sqlite3.Connection, origin: str, contained: Callable[[str], bool], *, members: FrozenSet[str] = frozenset(),
                    live: Optional[FrozenSet[str]] = None, offer: Optional[Tuple[str, Dict[str, Any]]] = None,
                    stale: bool = False) -> Optional[Tuple[str, int]]:
    if not capabilities.mesh_on() or live is None:
        if peer_hosts.get(conn, origin) is not None and not contained(origin):
            return ("", 1)
        best: Optional[Tuple[int, str]] = None
        for forwarder, hops in conn.execute(f"SELECT forwarder_install_id, hops FROM {OFFERS_TABLE} WHERE origin_install_id = ?", (origin,)):
            if not isinstance(hops, int) or hops + 1 > MAX_HOPS or contained(forwarder) or peer_hosts.get(conn, forwarder) is None:
                continue
            if best is None or (hops + 1, forwarder) < best:
                best = (hops + 1, forwarder)
        return None if best is None else (best[1], best[0])
    if (paired(conn, origin) or origin in members) and not contained(origin):
        return ("", 1)
    cands: Dict[str, int] = {}
    for forwarder, hops in conn.execute(f"SELECT forwarder_install_id, hops FROM {OFFERS_TABLE} WHERE origin_install_id = ?", (origin,)):
        if isinstance(hops, int) and hops + 1 <= MAX_HOPS and not contained(forwarder) and supplier_ok(conn, forwarder, members):
            cands[forwarder] = hops + 1
    ranked = min(((fwd not in live, hops, fwd) for fwd, hops in cands.items()), default=None)
    best_pick = None if ranked is None else (ranked[2], ranked[1])
    held = held_supplier(conn, origin)
    if held is None:
        return best_pick
    via, rev = held
    offered = offer[0] if offer is not None and offer[0] in cands and offer[0] in live else None
    seen = offer[1].get("revision") if offer is not None else None
    newer = offered is not None and isinstance(seen, int) and not isinstance(seen, bool) and seen > rev and offered != via
    if via in cands and via in live:
        return (offered, cands[offered]) if (stale and newer) else (via, cands[via])
    if (via == "" and not contained(origin)) or via in cands:
        if newer:
            return (offered, cands[offered])
        return ("", 1) if via == "" else (via, cands[via])
    return best_pick


def get_relay_state(conn: sqlite3.Connection, forwarder: str) -> Tuple[int, str]:
    row = conn.execute(f"SELECT revision, scope_digest FROM {RELAY_STATE_TABLE} WHERE forwarder_install_id = ?", (forwarder,)).fetchone()
    return (int(row[0]), str(row[1])) if row else (0, "")


def set_relay_state(conn: sqlite3.Connection, forwarder: str, revision: int, digest: str, now: float) -> None:
    conn.execute(
        f"INSERT INTO {RELAY_STATE_TABLE} (forwarder_install_id, revision, scope_digest, pulled_at, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(forwarder_install_id) DO UPDATE SET revision = excluded.revision, scope_digest = excluded.scope_digest, "
        "pulled_at = excluded.pulled_at, updated_at = excluded.updated_at", (forwarder, revision, digest, now, now))


def origins_via(conn: sqlite3.Connection, forwarder: str) -> List[str]:
    return sorted(supplied_through(conn, forwarder))


def paired(conn: sqlite3.Connection, install_id: str) -> bool:
    return peer_hosts.get(conn, install_id) is not None
