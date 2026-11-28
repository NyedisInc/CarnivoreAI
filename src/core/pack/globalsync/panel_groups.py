
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from src.core import session_group_style as style_store
from src.core.db import column_exists, table_exists
from src.core.db_models import SESSION_GROUP_MAX, SESSION_GROUP_NAME_MAX
from src.core.session_group_errors import GroupNameInvalid
from src.core.session_group_icon_ddl import ICON_COLUMN
from src.core.session_group_store import normalize_name
from src.core.session_group_style_ddl import SESSION_GROUP_STYLES_TABLE
from src.core.session_groups import session_group_rule as rule_store
from src.core.session_groups.session_group_parent import GroupParentInvalid, PARENT_COLUMN, normalize_parent_key
from src.core.trail_entry import utc_now

UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PORTABLE_UID = re.compile(r"[0-9a-f]{32}")
MAX_GROUPS = SESSION_GROUP_MAX
MAX_TOMBS = 500
MAX_ICON_LEN = 64
LocalKeys = Callable[[Any], List[str]]


def _ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "session_groups") and table_exists(conn, "session_group_membership")


def _portable_parent_key(
    raw: Optional[str],
    cid_uid: Mapping[int, str],
    pid_uid: Mapping[int, str],
) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if not key:
        return None
    if key.startswith("c:") and key[2:].isdigit():
        uid = cid_uid.get(int(key[2:]))
        return f"cu:{uid}" if uid else None
    if key.startswith("p:") and key[2:].isdigit():
        uid = pid_uid.get(int(key[2:]))
        return f"pu:{uid}" if uid else None
    return key


def _local_parent_key(
    raw: Any,
    uid_cid: Mapping[str, int],
    uid_pid: Mapping[str, int],
) -> Tuple[bool, Optional[str]]:
    if raw is None:
        return True, None
    if not isinstance(raw, str):
        return False, None
    key = raw.strip()
    if not key:
        return True, None
    if key.startswith("cu:"):
        uid = key[3:]
        if not _PORTABLE_UID.fullmatch(uid) or uid not in uid_cid:
            return False, None
        return True, f"c:{uid_cid[uid]}"
    if key.startswith("pu:"):
        uid = key[3:]
        if not _PORTABLE_UID.fullmatch(uid) or uid not in uid_pid:
            return False, None
        return True, f"p:{uid_pid[uid]}"
    try:
        return True, normalize_parent_key(key)
    except GroupParentInvalid:
        return False, None


def _creates_parent_cycle(conn: sqlite3.Connection, group_uuid: str, parent_key: Optional[str]) -> bool:
    if parent_key is None or not parent_key.startswith("g:"):
        return False
    target = parent_key[2:]
    if target == group_uuid:
        return True
    seen: Set[str] = {group_uuid}
    cur: Optional[str] = target
    while cur is not None:
        if cur in seen:
            return True
        seen.add(cur)
        row = conn.execute(
            f"SELECT {PARENT_COLUMN} FROM session_groups WHERE group_uuid = ?",
            (cur,),
        ).fetchone()
        if row is None or not isinstance(row[0], str) or not row[0].startswith("g:"):
            break
        cur = row[0][2:]
    return False


def _valid_icon_value(raw: Any) -> Tuple[bool, Optional[str]]:
    if raw is None:
        return True, None
    if isinstance(raw, str) and 0 < len(raw) <= MAX_ICON_LEN and raw.strip() == raw and raw.isprintable():
        return True, raw
    return False, None


def _parse_style(raw: Any) -> Optional[Tuple[str, Optional[str], str]]:
    if not isinstance(raw, Mapping):
        return None
    colour = raw.get("colour")
    gradient = raw.get("gradient")
    animation = raw.get("animation", "none")
    try:
        style_store.validate(colour, gradient, animation)
    except style_store.GroupStyleInvalid:
        return None
    return style_store.canonical_colour(str(colour)), gradient, str(animation)


def collect(
    conn: sqlite3.Connection,
    portable: Callable[[Any], List[List[str]]],
    bands: Mapping[str, Any],
    known: Collection[str] = (),
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not _ready(conn):
        return [], []
    members: Dict[int, List[str]] = {}
    for gid, uuid in conn.execute("SELECT group_id, session_uuid FROM session_group_membership ORDER BY group_id, position, session_uuid"):
        members.setdefault(int(gid), []).append(str(uuid))
    cid_uid: Dict[int, str] = (
        {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, uid FROM companies WHERE uid IS NOT NULL")}
        if table_exists(conn, "companies")
        else {}
    )
    pid_uid: Dict[int, str] = (
        {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, uid FROM projects WHERE uid IS NOT NULL")}
        if table_exists(conn, "projects")
        else {}
    )
    styles = style_store.styles_by_group(conn)
    rules = rule_store.rules_by_group(conn)
    has_parent = column_exists(conn, "session_groups", PARENT_COLUMN)
    parent_sel = f", {PARENT_COLUMN}" if has_parent else ", NULL AS parent_key"
    groups: List[Dict[str, Any]] = []
    for r in conn.execute(f"SELECT id, group_uuid, name{parent_sel} FROM session_groups ORDER BY position, group_uuid"):
        gid = int(r["id"])
        st = styles.get(gid)
        style_val = (
            {"colour": st.colour, "gradient": st.gradient, "animation": st.animation}
            if st is not None
            else None
        )
        icon_val = st.icon if st is not None else None
        entry: Dict[str, Any] = {
            "uid": r["group_uuid"],
            "name": r["name"],
            "members": portable(members.get(gid, [])),
            "band": portable(bands.get(f"g:{r['group_uuid']}")),
            "style": style_val,
            "icon": icon_val,
            "rule": rules.get(gid),
            "gone": False,
        }
        if has_parent:
            entry["parent_key"] = _portable_parent_key(r["parent_key"], cid_uid, pid_uid)
        groups.append(entry)
    order = [g["uid"] for g in groups]
    recency = known if isinstance(known, Mapping) else {}
    gone = sorted(
        (u for u in set(known) - set(order) if isinstance(u, str) and UID.fullmatch(u)),
        key=lambda u: (-recency.get(u, 0), u),
    )
    groups += [
        {"uid": uid, "name": None, "members": None, "band": None, "parent_key": None, "style": None, "icon": None, "rule": None, "gone": True}
        for uid in gone[:MAX_TOMBS]
    ]
    return groups, order


def _add_group(
    conn: sqlite3.Connection,
    uid: str,
    name: str,
    stamp: str,
    parent_key: Optional[str] = None,
    *,
    style_provided: bool = False,
    parsed_style: Optional[Tuple[str, Optional[str], str]] = None,
) -> int:
    top = conn.execute("SELECT COALESCE(MAX(position), -1) FROM session_groups").fetchone()[0]
    if column_exists(conn, "session_groups", PARENT_COLUMN):
        gid = conn.execute(
            "INSERT INTO session_groups (group_uuid, name, position, created_at, updated_at, parent_key) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, name, int(top) + 1, stamp, stamp, parent_key),
        ).lastrowid
    else:
        gid = conn.execute(
            "INSERT INTO session_groups (group_uuid, name, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (uid, name, int(top) + 1, stamp, stamp),
        ).lastrowid
    if table_exists(conn, SESSION_GROUP_STYLES_TABLE):
        if parsed_style is not None:
            style_store.write(conn, int(gid), parsed_style[0], parsed_style[1], parsed_style[2], now=stamp)
        elif not style_provided:
            style_store.write(conn, int(gid), style_store.random_colour(), now=stamp)
    return int(gid)


def _apply_style(conn: sqlite3.Connection, gid: int, raw_style: Any, stamp: str) -> bool:
    if not table_exists(conn, SESSION_GROUP_STYLES_TABLE):
        return False
    if raw_style is None:
        return False
    parsed = _parse_style(raw_style)
    if parsed is None:
        return False
    existing = conn.execute(
        f"SELECT colour, gradient, animation FROM {SESSION_GROUP_STYLES_TABLE} WHERE group_id = ?",
        (gid,),
    ).fetchone()
    if existing is not None and (existing[0], existing[1], existing[2]) == parsed:
        return False
    style_store.write(conn, gid, parsed[0], parsed[1], parsed[2], now=stamp)
    return True


def _apply_icon(conn: sqlite3.Connection, gid: int, uid: str, raw_icon: Any, stamp: str) -> bool:
    if not (table_exists(conn, SESSION_GROUP_STYLES_TABLE) and column_exists(conn, SESSION_GROUP_STYLES_TABLE, ICON_COLUMN)):
        return False
    ok, icon_val = _valid_icon_value(raw_icon)
    if not ok:
        return False
    existing = conn.execute(
        f"SELECT {ICON_COLUMN} FROM {SESSION_GROUP_STYLES_TABLE} WHERE group_id = ?",
        (gid,),
    ).fetchone()
    cur_icon = existing[0] if existing is not None and isinstance(existing[0], str) and existing[0] else None
    if cur_icon == icon_val:
        return False
    if icon_val is None:
        if existing is not None:
            conn.execute(
                f"UPDATE {SESSION_GROUP_STYLES_TABLE} SET {ICON_COLUMN} = NULL, updated_at = ? WHERE group_id = ?",
                (stamp, gid),
            )
            return True
        return False
    style_store.write_icon(conn, gid, uid, icon_val, now=stamp)
    return True


def _apply_rule(conn: sqlite3.Connection, gid: int, raw_rule: Any, cur_rules: Mapping[int, Dict[str, object]], stamp: str) -> bool:
    if not table_exists(conn, rule_store.RULE_TABLE):
        return False
    if raw_rule is None:
        norm_rule: Optional[Dict[str, object]] = None
    elif isinstance(raw_rule, Mapping):
        try:
            norm_rule = rule_store.normalize(raw_rule.get("flags"), raw_rule.get("prefix"), raw_rule.get("suffix"))
        except rule_store.GroupRuleInvalid:
            return False
    else:
        return False
    if cur_rules.get(gid) == norm_rule:
        return False
    rule_store.write(conn, gid, norm_rule, now=stamp)
    return True


def _set_members(conn: sqlite3.Connection, gid: int, wanted: Sequence[str], stamp: str) -> bool:
    rows = conn.execute("SELECT session_uuid FROM session_group_membership WHERE group_id = ? ORDER BY position, session_uuid", (gid,)).fetchall()
    have = [str(r[0]) for r in rows]
    other = {str(u) for (u,) in conn.execute("SELECT session_uuid FROM session_group_membership WHERE group_id != ?", (gid,))}
    if have == list(wanted) and not (set(wanted) & other):
        return False
    conn.execute("DELETE FROM session_group_membership WHERE group_id = ?", (gid,))
    for uuid in wanted:
        conn.execute("DELETE FROM session_group_membership WHERE session_uuid = ?", (uuid,))
    for index, uuid in enumerate(wanted):
        conn.execute("INSERT INTO session_group_membership (session_uuid, group_id, position, added_at) VALUES (?, ?, ?, ?)", (uuid, gid, index, stamp))
    return True


def apply(
    conn: sqlite3.Connection,
    items: Any,
    order: Any,
    local_keys: LocalKeys,
    report: Dict[str, Any],
    stamps: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Optional[List[List[str]]]]:
    decided: Dict[str, Optional[List[List[str]]]] = {}
    if not _ready(conn):
        return decided
    stamp = utc_now()
    listed = [i for i in (items if isinstance(items, list) else [])[:MAX_GROUPS + MAX_TOMBS] if isinstance(i, Mapping)]
    listed.sort(key=lambda i: (stamps or {}).get(i.get("uid"), (0, "")))
    has_parent = column_exists(conn, "session_groups", PARENT_COLUMN)
    uid_cid: Dict[str, int] = (
        {str(r[1]): int(r[0]) for r in conn.execute("SELECT id, uid FROM companies WHERE uid IS NOT NULL")}
        if has_parent and table_exists(conn, "companies")
        else {}
    )
    uid_pid: Dict[str, int] = (
        {str(r[1]): int(r[0]) for r in conn.execute("SELECT id, uid FROM projects WHERE uid IS NOT NULL")}
        if has_parent and table_exists(conn, "projects")
        else {}
    )
    cur_rules = rule_store.rules_by_group(conn)
    for item in listed:
        uid = item.get("uid")
        if not isinstance(uid, str) or not UID.fullmatch(uid):
            continue
        row = conn.execute(
            f"SELECT id, name{', parent_key' if has_parent else ', NULL AS parent_key'} FROM session_groups WHERE group_uuid = ?",
            (uid,),
        ).fetchone()
        if item.get("gone") is True:
            decided[uid] = None
            if row is not None:
                if has_parent:
                    conn.execute("UPDATE session_groups SET parent_key = ?, updated_at = ? WHERE parent_key = ?", (row["parent_key"], stamp, f"g:{uid}"))
                conn.execute("DELETE FROM session_group_membership WHERE group_id = ?", (row["id"],))
                conn.execute("DELETE FROM session_groups WHERE id = ?", (row["id"],))
                report["groups_changed"] += 1
            continue
        try:
            name = normalize_name(item["name"]) if isinstance(item.get("name"), str) else None
        except GroupNameInvalid:
            name = None
            report["skipped"].append(["group_name_invalid", str(item.get("name"))[:SESSION_GROUP_NAME_MAX]])
        parent_provided = False
        parent_key: Optional[str] = None
        if has_parent and "parent_key" in item:
            parent_provided, parent_key = _local_parent_key(item.get("parent_key"), uid_cid, uid_pid)
            if parent_provided and _creates_parent_cycle(conn, uid, parent_key):
                parent_provided = False
        style_provided = "style" in item
        parsed_style = _parse_style(item.get("style")) if style_provided else None
        if row is None:
            if name is None:
                continue
            if conn.execute("SELECT COUNT(*) FROM session_groups").fetchone()[0] >= MAX_GROUPS:
                report["skipped"].append(["group_limit_reached", name])
                continue
            gid = _add_group(
                conn,
                uid,
                name,
                stamp,
                parent_key if parent_provided else None,
                style_provided=style_provided,
                parsed_style=parsed_style,
            )
            changed = True
        else:
            gid, changed = int(row["id"]), False
            if name is not None and name != row["name"]:
                conn.execute("UPDATE session_groups SET name = ?, updated_at = ? WHERE id = ?", (name, stamp, gid))
                changed = True
            if has_parent and parent_provided and parent_key != row["parent_key"] and parent_key != f"g:{uid}":
                conn.execute("UPDATE session_groups SET parent_key = ?, updated_at = ? WHERE id = ?", (parent_key, stamp, gid))
                changed = True
            if style_provided:
                changed = _apply_style(conn, gid, item.get("style"), stamp) or changed
        if "icon" in item:
            changed = _apply_icon(conn, gid, uid, item.get("icon"), stamp) or changed
        if "rule" in item:
            changed = _apply_rule(conn, gid, item.get("rule"), cur_rules, stamp) or changed
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
