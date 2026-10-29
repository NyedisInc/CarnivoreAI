
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from src.cplugs.huddle import rules, sends

COLUMN = "owner_session_key"
TAG_COLUMN = "tagged_session_key"
FIELD = "owned_by"
TAGGED_BY = "tagged_by"
REASON_OWNER = "owner"


def clear(conn: sqlite3.Connection, item_ids: Sequence[int]) -> None:
    if item_ids:
        conn.execute(f"UPDATE work_items SET {COLUMN} = '' WHERE id IN ({','.join('?' * len(item_ids))})", list(item_ids))


def adopt_asker(conn: sqlite3.Connection, item_id: int, asker_key: str) -> bool:
    if not asker_key or asker_key == rules.SWARM_KEY:
        return False
    return bool(conn.execute(f"UPDATE work_items SET {COLUMN} = ? WHERE id = ? AND {COLUMN} = ''", (asker_key, item_id)).rowcount)


def keep_for_tell(conn: sqlite3.Connection, row: Mapping) -> bool:
    owner = row[COLUMN]
    if not owner or owner == rules.SWARM_KEY or row[TAG_COLUMN]:
        return False
    return bool(conn.execute(f"UPDATE work_items SET {COLUMN} = ? WHERE id = ? AND {COLUMN} = ''", (owner, row["id"])).rowcount)


def release_told(conn: sqlite3.Connection, list_keys: Sequence[str], cursor: int) -> int:
    keys = list(list_keys)
    if not keys:
        return 0
    states = sorted(rules.APPROVED_STATES)
    return conn.execute(f"UPDATE work_items SET {COLUMN} = '' WHERE {COLUMN} != '' AND state IN ({','.join('?' * len(states))}) "
                        f"AND joe_seq <= ? AND list_key IN ({','.join('?' * len(keys))})", [*states, cursor, *keys]).rowcount


def wire(row: Mapping) -> Dict[str, str]:
    return {COLUMN: row[COLUMN], TAG_COLUMN: row[TAG_COLUMN]}


def route_key(row: Mapping) -> str:
    return row[TAG_COLUMN] or row[COLUMN]


def untold_rows(conn: sqlite3.Connection, list_key: str) -> List[Tuple[int, str, str]]:
    rows = conn.execute(
        f"SELECT id, {TAG_COLUMN}, {COLUMN} FROM work_items WHERE list_key = ? AND deleted = 0 AND {sends.sendable_sql()} AND joe_seq > "
        "COALESCE((SELECT t.cursor FROM work_sends t WHERE t.list_key = work_items.list_key), 0) ORDER BY id", (list_key,)).fetchall()
    return [(int(r[0]), r[1] or "", r[2] or "") for r in rows]


def untold_items(conn: sqlite3.Connection, list_key: str) -> List[Tuple[int, str]]:
    return [(item_id, tag or owner) for item_id, tag, owner in untold_rows(conn, list_key)]


def live_id(owner_key: str, rows: Sequence[Mapping]) -> Optional[str]:
    if not owner_key:
        return None
    return next((r["id"] for r in rows if owner_key in (r["key"], r["id"])), None)


@dataclass
class Part:

    target: Optional[str]
    reason: str
    items: List[int] = field(default_factory=list)


@dataclass
class Split:

    parts: List[Part]
    gone: Dict[int, str]

    @property
    def divided(self) -> bool:
        return any(p.reason == REASON_OWNER for p in self.parts)


def split(untold: Sequence[Tuple[int, str]], rows: Sequence[Mapping], default: Optional[str], reason: str) -> Split:
    owned: Dict[str, List[int]] = {}
    rest: List[int] = []
    gone: Dict[int, str] = {}
    for item_id, owner_key in untold:
        target = live_id(owner_key, rows)
        if owner_key and target is None:
            gone[item_id] = owner_key
        if target is None or target == default:
            rest.append(item_id)
        else:
            owned.setdefault(target, []).append(item_id)
    parts = [Part(target, REASON_OWNER, ids) for target, ids in owned.items()]
    if rest or not parts:
        parts.append(Part(default, reason, rest))
    return Split(parts, gone)


__all__ = ["COLUMN", "TAG_COLUMN", "TAGGED_BY", "route_key", "adopt_asker", "keep_for_tell", "release_told", "FIELD", "REASON_OWNER", "Part", "Split", "wire", "untold_rows", "untold_items", "live_id", "split"]
