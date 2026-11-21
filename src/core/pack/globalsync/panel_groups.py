
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from src.core.db import table_exists
from src.core.db_models import SESSION_GROUP_MAX, SESSION_GROUP_NAME_MAX
from src.core.session_group_errors import GroupNameInvalid
from src.core.session_group_membership import LAYOUT_MEMBER_PREFIX
from src.core.session_group_store import normalize_name
from src.core.trail_entry import utc_now

UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MAX_GROUPS = SESSION_GROUP_MAX
MAX_TOMBS = 500
LocalKeys = Callable[[Any], List[str]]


def _ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "session_groups") and table_exists(conn, "session_group_membership")


def collect(conn: sqlite3.Connection, portable: Callable[[Any], List[List[str]]], bands: Mapping[str, Any],
            known: Collection[str] = ()) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not _ready(conn):
        return [], []
    members: Dict[int, List[str]] = {}
    for gid, uuid in conn.execute("SELECT group_id, session_uuid FROM session_group_membership ORDER BY group_id, position, session_uuid"):
        if not uuid.startswith(LAYOUT_MEMBER_PREFIX):
            members.setdefault(gid, []).append(uuid)
    groups = [{"uid": r["group_uuid"], "name": r["name"], "members": portable(members.get(r["id"], [])),
               "band": portable(bands.get(f"g:{r['group_uuid']}")), "gone": False}
              for r in conn.execute("SELECT id, group_uuid, name FROM session_groups ORDER BY position, group_uuid")]
    order = [g["uid"] for g in groups]
    recency = known if isinstance(known, Mapping) else {}
    gone = sorted((u for u in set(known) - set(order) if isinstance(u, str) and UID.fullmatch(u)), key=lambda u: (-recency.get(u, 0), u))
    groups += [{"uid": uid, "name": None, "members": None, "band": None, "gone": True} for uid in gone[:MAX_TOMBS]]
    return groups, order


def _add_group(conn: sqlite3.Connection, uid: str, name: str, stamp: str) -> int:
    top = conn.execute("SELECT COALESCE(MAX(position), -1) FROM session_groups").fetchone()[0]
    gid = conn.execute("INSERT INTO session_groups (group_uuid, name, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                       (uid, name, int(top) + 1, stamp, stamp)).lastrowid
    from src.core import session_group_style as style_store
    from src.core.session_group_style_ddl import SESSION_GROUP_STYLES_TABLE
    if table_exists(conn, SESSION_GROUP_STYLES_TABLE):
        style_store.write(conn, gid, style_store.random_colour(), now=stamp)
    return int(gid)


def _set_members(conn: sqlite3.Connection, gid: int, wanted: Sequence[str], stamp: str) -> bool:
    rows = conn.execute("SELECT session_uuid FROM session_group_membership WHERE group_id = ? ORDER BY position, session_uuid", (gid,)).fetchall()
    have = [r[0] for r in rows if not r[0].startswith(LAYOUT_MEMBER_PREFIX)]
    other = {u for (u,) in conn.execute("SELECT session_uuid FROM session_group_membership WHERE group_id != ?", (gid,))}
    if have == list(wanted) and not (set(wanted) & other):
        return False
    layouts = [r[0] for r in rows if r[0].startswith(LAYOUT_MEMBER_PREFIX)]
    conn.execute("DELETE FROM session_group_membership WHERE group_id = ?", (gid,))
    for uuid in wanted:
        conn.execute("DELETE FROM session_group_membership WHERE session_uuid = ?", (uuid,))
    for index, uuid in enumerate([*wanted, *layouts]):
        conn.execute("INSERT INTO session_group_membership (session_uuid, group_id, position, added_at) VALUES (?, ?, ?, ?)", (uuid, gid, index, stamp))
    return True


def apply(conn: sqlite3.Connection, items: Any, order: Any, local_keys: LocalKeys, report: Dict[str, Any],
          stamps: Optional[Mapping[str, Any]] = None) -> Dict[str, Optional[List[List[str]]]]:
    decided: Dict[str, Optional[List[List[str]]]] = {}
    if not _ready(conn):
        return decided
    stamp = utc_now()
    listed = [i for i in (items if isinstance(items, list) else [])[:MAX_GROUPS + MAX_TOMBS] if isinstance(i, Mapping)]
    listed.sort(key=lambda i: (stamps or {}).get(i.get("uid"), (0, "")))
    for item in listed:
        uid = item.get("uid")
        if not isinstance(uid, str) or not UID.fullmatch(uid):
            continue
        row = conn.execute("SELECT id, name FROM session_groups WHERE group_uuid = ?", (uid,)).fetchone()
        if item.get("gone") is True:
            decided[uid] = None
            if row is not None:
                conn.execute("DELETE FROM session_group_membership WHERE group_id = ?", (row["id"],))
                conn.execute("DELETE FROM session_groups WHERE id = ?", (row["id"],))
                report["groups_changed"] += 1
            continue
        try:
            name = normalize_name(item["name"]) if isinstance(item.get("name"), str) else None
        except GroupNameInvalid:
            name = None
            report["skipped"].append(["group_name_invalid", str(item.get("name"))[:SESSION_GROUP_NAME_MAX]])
        if row is None:
            if name is None:
                continue
            if conn.execute("SELECT COUNT(*) FROM session_groups").fetchone()[0] >= MAX_GROUPS:
                report["skipped"].append(["group_limit_reached", name])
                continue
            gid, changed = _add_group(conn, uid, name, stamp), True
        else:
            gid, changed = int(row["id"]), False
            if name is not None and name != row["name"]:
                conn.execute("UPDATE session_groups SET name = ?, updated_at = ? WHERE id = ?", (name, stamp, gid))
                changed = True
        if isinstance(item.get("members"), list):
            changed = _set_members(conn, gid, local_keys(item["members"]), stamp) or changed
        if isinstance(item.get("band"), list):
            decided[uid] = item["band"]
        report["groups_changed"] += 1 if changed else 0
    if isinstance(order, list):
        ids = {r[0]: r[1] for r in conn.execute("SELECT group_uuid, id FROM session_groups")}
        wanted = list(dict.fromkeys(u for u in order[:MAX_GROUPS * 2] if isinstance(u, str) and u in ids))
        rest = [r[0] for r in conn.execute("SELECT group_uuid FROM session_groups ORDER BY position, group_uuid") if r[0] not in wanted]
        current = [r[0] for r in conn.execute("SELECT group_uuid FROM session_groups ORDER BY position, group_uuid")]
        if current != wanted + rest:
            for index, uid in enumerate(wanted + rest):
                conn.execute("UPDATE session_groups SET position = ? WHERE id = ?", (index, ids[uid]))
            report["groups_changed"] += 1
    return decided


def member_keys(conn: sqlite3.Connection) -> Set[str]:
    if not _ready(conn):
        return set()
    return {r[0] for r in conn.execute("SELECT session_uuid FROM session_group_membership")}
