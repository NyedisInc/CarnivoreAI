
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from src.core.db import table_exists
from src.core.layouts import store as layouts_store
from src.core.layouts import style as layout_style
from src.core.layouts.broadcast_ddl import LAYOUT_BROADCAST_OFF_TABLE
from src.core.layouts.ddl import LAYOUT_MEMBERS_TABLE, LAYOUTS_TABLE
from src.core.layouts.style_ddl import LAYOUT_STYLES_TABLE
from src.core.session_group_membership import LAYOUT_MEMBER_PREFIX
from src.core.trail_entry import utc_now

UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MAX_LAYOUTS = layouts_store.LAYOUT_MAX
MAX_TOMBS = 500
_ROW_SLOT = re.compile(r"^terminal:row:(\d{1,15})$")
_PEER_SLOT = re.compile(r"^terminal:peer:([^/]+)/([^/]+)$")

PortableFn = Callable[[Any], List[List[str]]]
LocalMemberFn = Callable[[str, str], str]


def _ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, LAYOUTS_TABLE) and table_exists(conn, LAYOUT_MEMBERS_TABLE)


def _safe_json_loads(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _rewrite_strings(obj: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_rewrite_strings(item, fn) for item in obj]
    if isinstance(obj, dict):
        return {fn(k) if isinstance(k, str) else k: _rewrite_strings(v, fn) for k, v in obj.items()}
    return obj


def _encode_shape(raw_shape: Any, row_to_pair: Mapping[int, List[str]]) -> Dict[str, Any]:
    parsed = _safe_json_loads(raw_shape)
    if parsed is None:
        return {"layout": None, "groups": {}}

    def _to_peer(text: str) -> str:
        match = _ROW_SLOT.match(text)
        if match is None:
            return text
        pair = row_to_pair.get(int(match.group(1)))
        if pair is None:
            return text
        return f"terminal:peer:{pair[0]}/{pair[1]}"

    return _rewrite_strings(parsed, _to_peer)


def _decode_shape(raw_shape: Any, local_member_fn: LocalMemberFn, suuid_to_rowid: Mapping[str, int]) -> Optional[Dict[str, Any]]:
    parsed = _safe_json_loads(raw_shape)
    if parsed is None:
        return None

    def _to_row(text: str) -> str:
        match = _PEER_SLOT.match(text)
        if match is None:
            return text
        local_suuid = local_member_fn(match.group(1), match.group(2))
        row_id = suuid_to_rowid.get(local_suuid)
        if row_id is None:
            return text
        return f"terminal:row:{row_id}"

    return _rewrite_strings(parsed, _to_row)


def collect(
    conn: sqlite3.Connection,
    portable: PortableFn,
    known: Collection[str] = (),
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not _ready(conn):
        return [], []
    row_to_pair: Dict[int, List[str]] = {}
    if table_exists(conn, "sessions"):
        for row_id, suuid in conn.execute("SELECT id, session_uuid FROM sessions"):
            pairs = portable([suuid])
            if pairs:
                row_to_pair[int(row_id)] = pairs[0]
    broadcast_off: Set[Tuple[int, int]] = set()
    if table_exists(conn, LAYOUT_BROADCAST_OFF_TABLE):
        broadcast_off = {
            (int(r[0]), int(r[1]))
            for r in conn.execute(f"SELECT layout_id, session_row_id FROM {LAYOUT_BROADCAST_OFF_TABLE}")
        }
    members_by_layout: Dict[int, List[List[Any]]] = {}
    for lid, row_id, suuid in conn.execute(
        "SELECT m.layout_id, m.session_row_id, s.session_uuid "
        "FROM layout_members m JOIN sessions s ON s.id = m.session_row_id "
        "ORDER BY m.layout_id ASC, m.position ASC, m.session_row_id ASC"
    ):
        pair = row_to_pair.get(int(row_id))
        if pair is None:
            pairs = portable([suuid])
            if not pairs:
                continue
            pair = pairs[0]
        bc = (int(lid), int(row_id)) not in broadcast_off
        members_by_layout.setdefault(int(lid), []).append([pair[0], pair[1], bc])
    styles = layout_style.styles_by_layout(conn)
    layouts: List[Dict[str, Any]] = []
    for row in conn.execute(
        f"SELECT id, layout_uuid, name, shape FROM {LAYOUTS_TABLE} ORDER BY position ASC, layout_uuid ASC"
    ):
        lid = int(row["id"])
        luuid = str(row["layout_uuid"])
        st = styles.get(luuid)
        style_val = (
            {"colour": st.colour, "gradient": st.gradient, "animation": st.animation}
            if st is not None
            else None
        )
        layouts.append({
            "uid": luuid,
            "name": str(row["name"]),
            "shape": _encode_shape(row["shape"], row_to_pair),
            "style": style_val,
            "members": members_by_layout.get(lid, []),
            "gone": False,
        })
    order = [ly["uid"] for ly in layouts]
    recency = known if isinstance(known, Mapping) else {}
    gone = sorted(
        (u for u in set(known) - set(order) if isinstance(u, str) and UID.fullmatch(u)),
        key=lambda u: (-recency.get(u, 0), u),
    )
    layouts += [
        {"uid": uid, "name": None, "shape": None, "style": None, "members": None, "gone": True}
        for uid in gone[:MAX_TOMBS]
    ]
    return layouts, order


def _apply_style(conn: sqlite3.Connection, uid: str, raw_style: Any, stamp: str) -> bool:
    if not table_exists(conn, LAYOUT_STYLES_TABLE):
        return False
    existing = conn.execute(
        f"SELECT colour, gradient, animation FROM {LAYOUT_STYLES_TABLE} WHERE layout_uuid = ?",
        (uid,),
    ).fetchone()
    if raw_style is None:
        if existing is not None:
            conn.execute(f"DELETE FROM {LAYOUT_STYLES_TABLE} WHERE layout_uuid = ?", (uid,))
            return True
        return False
    if not isinstance(raw_style, Mapping):
        return False
    colour = raw_style.get("colour")
    gradient = raw_style.get("gradient")
    animation = raw_style.get("animation", "none")
    try:
        layout_style.validate(colour, gradient, animation)
    except layout_style.LayoutStyleInvalid:
        return False
    canon = layout_style.canonical_colour(str(colour))
    if existing is not None and (existing[0], existing[1], existing[2]) == (canon, gradient, animation):
        return False
    layout_style.write(conn, uid, canon, gradient, str(animation), now=stamp)
    return True


def _apply_members(
    conn: sqlite3.Connection,
    layout_id: int,
    raw_members: Sequence[Any],
    local_member_fn: LocalMemberFn,
    suuid_to_rowid: Mapping[str, int],
    stamp: str,
) -> bool:
    wanted: List[Tuple[int, bool]] = []
    seen_ids: Set[int] = set()
    for entry in raw_members:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        origin_iid, origin_suuid = entry[0], entry[1]
        if not (isinstance(origin_iid, str) and isinstance(origin_suuid, str) and origin_iid and origin_suuid):
            continue
        bc = entry[2] if len(entry) >= 3 and isinstance(entry[2], bool) else True
        row_id = suuid_to_rowid.get(local_member_fn(origin_iid, origin_suuid))
        if row_id is None or row_id in seen_ids:
            continue
        seen_ids.add(row_id)
        wanted.append((row_id, bc))
    cur_ids = [
        int(r[0])
        for r in conn.execute(
            f"SELECT session_row_id FROM {LAYOUT_MEMBERS_TABLE} WHERE layout_id = ? ORDER BY position ASC, session_row_id ASC",
            (layout_id,),
        ).fetchall()
    ]
    wanted_ids = [rid for rid, _bc in wanted]
    changed = False
    if cur_ids != wanted_ids:
        if wanted_ids:
            marks = ",".join("?" for _ in wanted_ids)
            conn.execute(
                f"DELETE FROM {LAYOUT_MEMBERS_TABLE} WHERE layout_id = ? AND session_row_id NOT IN ({marks})",
                (layout_id, *wanted_ids),
            )
            for pos, row_id in enumerate(wanted_ids):
                conn.execute(
                    f"INSERT INTO {LAYOUT_MEMBERS_TABLE} (layout_id, session_row_id, position) VALUES (?, ?, ?) "
                    "ON CONFLICT(layout_id, session_row_id) DO UPDATE SET position = excluded.position",
                    (layout_id, row_id, pos),
                )
        else:
            conn.execute(f"DELETE FROM {LAYOUT_MEMBERS_TABLE} WHERE layout_id = ?", (layout_id,))
        changed = True
    if table_exists(conn, LAYOUT_BROADCAST_OFF_TABLE):
        cur_off = {
            int(r[0])
            for r in conn.execute(
                f"SELECT session_row_id FROM {LAYOUT_BROADCAST_OFF_TABLE} WHERE layout_id = ?",
                (layout_id,),
            ).fetchall()
        }
        wanted_off = {rid for rid, bc in wanted if not bc}
        if cur_off != wanted_off:
            for rid in cur_off - wanted_off:
                conn.execute(
                    f"DELETE FROM {LAYOUT_BROADCAST_OFF_TABLE} WHERE layout_id = ? AND session_row_id = ?",
                    (layout_id, rid),
                )
            for rid in wanted_off - cur_off:
                conn.execute(
                    f"INSERT OR IGNORE INTO {LAYOUT_BROADCAST_OFF_TABLE} (layout_id, session_row_id, updated_at) VALUES (?, ?, ?)",
                    (layout_id, rid, stamp),
                )
            changed = True
    return changed


def apply(
    conn: sqlite3.Connection,
    items: Any,
    order: Any,
    local_member_fn: LocalMemberFn,
    report: Dict[str, Any],
    stamps: Optional[Mapping[str, Any]] = None,
) -> None:
    report.setdefault("layouts_changed", 0)
    if not _ready(conn):
        return
    stamp = utc_now()
    listed = [i for i in (items if isinstance(items, list) else [])[:MAX_LAYOUTS + MAX_TOMBS] if isinstance(i, Mapping)]
    if stamps:
        listed.sort(key=lambda i: stamps.get(i.get("uid"), (0, "")))
    suuid_to_rowid: Dict[str, int] = (
        {str(r[1]): int(r[0]) for r in conn.execute("SELECT id, session_uuid FROM sessions")}
        if table_exists(conn, "sessions")
        else {}
    )
    for item in listed:
        uid = item.get("uid")
        if not isinstance(uid, str) or not UID.fullmatch(uid):
            continue
        row = conn.execute(
            f"SELECT id, name, shape FROM {LAYOUTS_TABLE} WHERE layout_uuid = ?",
            (uid,),
        ).fetchone()
        if item.get("gone") is True:
            if row is not None:
                lid = int(row["id"])
                if table_exists(conn, LAYOUT_BROADCAST_OFF_TABLE):
                    conn.execute(f"DELETE FROM {LAYOUT_BROADCAST_OFF_TABLE} WHERE layout_id = ?", (lid,))
                conn.execute(f"DELETE FROM {LAYOUT_MEMBERS_TABLE} WHERE layout_id = ?", (lid,))
                if table_exists(conn, LAYOUT_STYLES_TABLE):
                    conn.execute(f"DELETE FROM {LAYOUT_STYLES_TABLE} WHERE layout_uuid = ?", (uid,))
                conn.execute(f"DELETE FROM {LAYOUTS_TABLE} WHERE id = ?", (lid,))
                if table_exists(conn, "session_group_membership"):
                    conn.execute(
                        "DELETE FROM session_group_membership WHERE session_uuid = ?",
                        (f"{LAYOUT_MEMBER_PREFIX}{uid}",),
                    )
                report["layouts_changed"] += 1
            continue
        try:
            name = layouts_store.normalize_name(item["name"]) if isinstance(item.get("name"), str) else None
        except layouts_store.LayoutNameInvalid:
            name = None
            report["skipped"].append(["layout_name_invalid", str(item.get("name"))[:layouts_store.NAME_MAX]])
        decoded_shape = _decode_shape(item.get("shape"), local_member_fn, suuid_to_rowid) if "shape" in item else None
        if row is None:
            if name is None:
                continue
            if conn.execute(f"SELECT COUNT(*) FROM {LAYOUTS_TABLE}").fetchone()[0] >= MAX_LAYOUTS:
                report["skipped"].append(["layout_limit_reached", name])
                continue
            folded = layouts_store.fold_name(name)
            if conn.execute(f"SELECT 1 FROM {LAYOUTS_TABLE} WHERE name_fold = ?", (folded,)).fetchone():
                report["skipped"].append(["layout_name_taken", name])
                continue
            top = int(conn.execute(f"SELECT COALESCE(MAX(position), -1) FROM {LAYOUTS_TABLE}").fetchone()[0])
            shape_obj = decoded_shape if decoded_shape is not None else {"layout": None, "groups": {}}
            cur = conn.execute(
                f"INSERT INTO {LAYOUTS_TABLE} (layout_uuid, name, name_fold, position, shape, revision, source_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL, ?, ?)",
                (uid, name, folded, top + 1, json.dumps(shape_obj, sort_keys=True, separators=(",", ":")), stamp, stamp),
            )
            lid, changed = int(cur.lastrowid), True
        else:
            lid, changed = int(row["id"]), False
            if name is not None and name != row["name"]:
                folded = layouts_store.fold_name(name)
                if conn.execute(
                    f"SELECT 1 FROM {LAYOUTS_TABLE} WHERE name_fold = ? AND id != ?",
                    (folded, lid),
                ).fetchone():
                    report["skipped"].append(["layout_name_taken", name])
                else:
                    conn.execute(
                        f"UPDATE {LAYOUTS_TABLE} SET name = ?, name_fold = ?, updated_at = ? WHERE id = ?",
                        (name, folded, stamp, lid),
                    )
                    changed = True
            if decoded_shape is not None and decoded_shape != _safe_json_loads(row["shape"]):
                conn.execute(
                    f"UPDATE {LAYOUTS_TABLE} SET shape = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
                    (json.dumps(decoded_shape, sort_keys=True, separators=(",", ":")), stamp, lid),
                )
                changed = True
        if "style" in item:
            changed = _apply_style(conn, uid, item.get("style"), stamp) or changed
        if isinstance(item.get("members"), list):
            changed = _apply_members(conn, lid, item["members"], local_member_fn, suuid_to_rowid, stamp) or changed
        if changed:
            report["layouts_changed"] += 1
    if isinstance(order, list):
        ids = {str(r[0]): int(r[1]) for r in conn.execute(f"SELECT layout_uuid, id FROM {LAYOUTS_TABLE}")}
        wanted = list(dict.fromkeys(u for u in order[:MAX_LAYOUTS * 2] if isinstance(u, str) and u in ids))
        current = [
            str(r[0])
            for r in conn.execute(f"SELECT layout_uuid FROM {LAYOUTS_TABLE} ORDER BY position ASC, layout_uuid ASC")
        ]
        rest = [u for u in current if u not in wanted]
        if current != wanted + rest:
            for index, uid in enumerate(wanted + rest):
                conn.execute(f"UPDATE {LAYOUTS_TABLE} SET position = ? WHERE id = ?", (index, ids[uid]))
            report["layouts_changed"] += 1


def member_keys(conn: sqlite3.Connection) -> Set[str]:
    if not _ready(conn) or not table_exists(conn, "sessions"):
        return set()
    return {
        str(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT s.session_uuid FROM {LAYOUT_MEMBERS_TABLE} m JOIN sessions s ON s.id = m.session_row_id"
        )
    }
