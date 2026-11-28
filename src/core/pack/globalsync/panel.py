
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Collection, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import structlog

from src.core.db import table_exists
from src.core.db_models import PROJECT_SOURCE_USER
from src.core.federation.shadow_rows import shadow_uuid
from src.core.pack.globalsync import panel_groups, panel_layouts
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.project_colors.palette import is_hex_color
from src.core.project_lineage.parents import parent_project_ids
from src.core.trail_entry import utc_now
from src.core.ui_preferences.constants import ARRANGEMENT_SCHEMA_VERSION, MAX_REMEMBERED
from src.core.ui_preferences.drawer_arrangement import SECTION_IDS

logger = structlog.get_logger()

VERSION = 1
CAP = "pack.global_setup.panel"
MAX_COMPANIES, MAX_COMPANY_TOMBS, MAX_PROJECTS, MAX_NAME = 500, 500, 2000, 200
META_PACK_PROJECT_PARENTS = "peer_project_parents"
_UID = re.compile(r"[0-9a-f]{32}")
_PROJECT_BAND = re.compile(r"p:([0-9a-f]{32})")
_KIND_BANDS = frozenset({"rogue", "terminals", "browsers", "files", "review"})
_ARRANGEMENT_KEYS = ("pinned", "order", "bands", "sections")


def _columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _valid_uid(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _UID.fullmatch(value) else None


def _valid_install_id(value: Any) -> Optional[str]:
    if (isinstance(value, str) and 0 < len(value) <= 64 and value.strip() == value
            and value.isprintable() and "/" not in value and "\\" not in value and ".." not in value):
        return value
    return None


def synced_project_parents(conn: sqlite3.Connection) -> Dict[str, str]:
    if not table_exists(conn, "meta"):
        return {}
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (META_PACK_PROJECT_PARENTS,)).fetchone()
    if row is None or not isinstance(row[0], str):
        return {}
    try:
        raw = json.loads(row[0])
    except ValueError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if _valid_uid(k) and _valid_uid(v) and k != v}


def _save_synced_project_parents(conn: sqlite3.Connection, mapping: Mapping[str, str]) -> None:
    if not table_exists(conn, "meta"):
        return
    clean = {k: v for k, v in sorted(mapping.items()) if _valid_uid(k) and _valid_uid(v) and k != v}
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                 (META_PACK_PROJECT_PARENTS, json.dumps(clean, sort_keys=True, separators=(",", ":"))))


def _peer_host_maps(conn: sqlite3.Connection) -> Tuple[Dict[str, str], Dict[str, str]]:
    if not table_exists(conn, "hosts"):
        return {}, {}
    hcols = _columns(conn, "hosts")
    if "peer_install_id" not in hcols or "kind" not in hcols:
        return {}, {}
    order = "ORDER BY CASE WHEN COALESCE(peer_back_kind, '') = 'mesh' THEN 1 ELSE 0 END, key" if "peer_back_kind" in hcols else "ORDER BY key"
    host_to_iid: Dict[str, str] = {}
    iid_to_host: Dict[str, str] = {}
    for hkey, piid in conn.execute(f"SELECT key, peer_install_id FROM hosts WHERE kind = 'peer' AND peer_install_id IS NOT NULL {order}"):
        if isinstance(hkey, str) and isinstance(piid, str):
            host_to_iid[hkey] = piid
            iid_to_host.setdefault(piid, hkey)
    return host_to_iid, iid_to_host


def _project_home_iid(row: Mapping[str, Any], own_install_id: str, host_to_iid: Mapping[str, str]) -> Optional[str]:
    if row["host_key"] == LOCAL_HOST_KEY:
        if row["pack_state"] == "replica":
            return _valid_install_id(row["home_install_id"]) or _valid_install_id(own_install_id)
        if row["pack_state"] == "moved_away":
            return _valid_install_id(row["moved_to_install_id"]) or _valid_install_id(own_install_id)
        return _valid_install_id(own_install_id)
    return _valid_install_id(row["home_install_id"]) or _valid_install_id(host_to_iid.get(row["host_key"]))


def _session_keys(conn: sqlite3.Connection, own_install_id: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for uuid, origin, peer_uuid, peer_iid in conn.execute(
            "SELECT s.session_uuid, s.origin, ps.peer_session_uuid, h.peer_install_id FROM sessions s "
            "LEFT JOIN peer_sessions ps ON ps.session_id = s.id LEFT JOIN hosts h ON h.key = ps.host_key"):
        if origin == "peer":
            if peer_uuid and peer_iid:
                out[uuid] = [peer_iid, peer_uuid]
        else:
            out[uuid] = [own_install_id, uuid]
    return out


def collect(conn: sqlite3.Connection, arrangement: Optional[Mapping[str, Any]], own_install_id: str,
            stamped_uids: Collection[str] = (), all_projects: bool = False,
            extra_keys: Optional[Mapping[str, Sequence[str]]] = None, known_groups: Collection[str] = (),
            known_companies: Collection[str] = (), known_layouts: Collection[str] = ()) -> Dict[str, Any]:
    ccols = _columns(conn, "companies")
    cid_uid = {r[0]: r[1] for r in conn.execute("SELECT id, uid FROM companies WHERE uid IS NOT NULL")}
    companies = [{"uid": r["uid"], "name": r["name"], "parent_uid": cid_uid.get(r["parent_id"]) if "parent_id" in ccols else None,
                  "hue": r["hue"] if "hue" in ccols else None, "gone": False}
                 for r in conn.execute(f"SELECT uid, name, {'parent_id' if 'parent_id' in ccols else 'NULL AS parent_id'}, "
                                       f"{'hue' if 'hue' in ccols else 'NULL AS hue'} FROM companies WHERE uid IS NOT NULL ORDER BY id")]
    live_c_uids = {c["uid"] for c in companies}
    c_recency = known_companies if isinstance(known_companies, Mapping) else {}
    gone_c = sorted((u for u in set(known_companies) - live_c_uids if _valid_uid(u)), key=lambda u: (-c_recency.get(u, 0), u))
    companies += [{"uid": uid, "name": None, "parent_uid": None, "hue": None, "gone": True} for uid in gone_c[:MAX_COMPANY_TOMBS]]

    pcols = _columns(conn, "projects")
    opt_cols = [
        "short_description" if "short_description" in pcols else "NULL AS short_description",
        "archived_at" if "archived_at" in pcols else "NULL AS archived_at",
        "home_install_id" if "home_install_id" in pcols else "NULL AS home_install_id",
        "pack_state" if "pack_state" in pcols else "NULL AS pack_state",
        "moved_to_install_id" if "moved_to_install_id" in pcols else "NULL AS moved_to_install_id",
        "parent_uid" if "parent_uid" in pcols else "NULL AS parent_uid",
        "parent_project_id" if "parent_project_id" in pcols else "NULL AS parent_project_id",
    ]
    all_rows = conn.execute(
        f"SELECT id, uid, root, display_name, company_id, color, host_key, {', '.join(opt_cols)} FROM projects "
        "WHERE uid IS NOT NULL ORDER BY id"
    ).fetchall()
    pid_uid = {r["id"]: r["uid"] for r in all_rows}
    derived_parents = parent_project_ids(
        [{"id": r["id"], "root": r["root"], "host_key": r["host_key"], "archived_at": r["archived_at"]} for r in all_rows]
    )
    stored_parents = synced_project_parents(conn)
    host_to_iid, _iid_to_host = _peer_host_maps(conn)
    rows = [r for r in all_rows if all_projects or r["host_key"] == LOCAL_HOST_KEY or r["uid"] in stamped_uids]

    def _parent_uid_of(r: Any) -> Optional[str]:
        if "parent_uid" in pcols and _valid_uid(r["parent_uid"]):
            return r["parent_uid"]
        if "parent_project_id" in pcols and r["parent_project_id"] in pid_uid:
            return pid_uid[r["parent_project_id"]]
        if r["host_key"] == LOCAL_HOST_KEY:
            parent_pid = derived_parents.get(r["id"])
            return pid_uid.get(parent_pid) if parent_pid is not None else None
        return stored_parents.get(r["uid"])

    projects = [{"uid": r["uid"], "name": r["display_name"], "company_uid": cid_uid.get(r["company_id"]), "color": r["color"],
                 "short_description": r["short_description"], "archived": bool(r["archived_at"]),
                 "parent_uid": _parent_uid_of(r), "home_iid": _project_home_iid(r, own_install_id, host_to_iid)} for r in rows]
    keys = {**{k: list(v) for k, v in (extra_keys or {}).items()}, **_session_keys(conn, own_install_id)}
    arr = arrangement if isinstance(arrangement, Mapping) else {}

    def portable(uuids: Any) -> List[List[str]]:
        out: List[List[str]] = []
        for u in uuids if isinstance(uuids, list) else []:
            if not isinstance(u, str):
                continue
            if u.startswith("layout:") and 7 < len(u) <= 71:
                out.append(["layout", u[7:]])
            elif u in keys:
                out.append(keys[u])
        return out

    bands: Dict[str, List[List[str]]] = {}
    for key, members in (arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}).items():
        if key in _KIND_BANDS:
            bands[key] = portable(members)
        elif isinstance(key, str) and key.startswith("p:") and key[2:].isdigit() and int(key[2:]) in pid_uid:
            bands[f"p:{pid_uid[int(key[2:])]}"] = portable(members)
    sections = arr.get("sections") if isinstance(arr.get("sections"), list) else None
    layouts, layout_order = panel_layouts.collect(conn, portable, known_layouts)
    groups, group_order = panel_groups.collect(conn, portable, arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}, known_groups)
    return {"v": VERSION, "companies": companies, "projects": projects, "groups": groups, "layouts": layouts,
            "arrangement": {"group_order": group_order, "layout_order": layout_order, "pinned": portable(arr.get("pinned")),
                            "order": portable(arr.get("order")), "bands": bands, "sections": sections}}


def _text(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= MAX_NAME else None


def _upsert_companies(conn: sqlite3.Connection, rows: Sequence[Any], report: Dict[str, Any]) -> Dict[str, int]:
    ccols = _columns(conn, "companies")
    ids: Dict[str, int] = {}
    stamp = utc_now()
    live_seen = gone_seen = 0
    live_items: List[Mapping[str, Any]] = []
    for item in rows[:MAX_COMPANIES + MAX_COMPANY_TOMBS]:
        if not isinstance(item, Mapping):
            continue
        uid = _valid_uid(item.get("uid"))
        if uid is None:
            continue
        if item.get("gone") is True:
            if gone_seen >= MAX_COMPANY_TOMBS:
                continue
            gone_seen += 1
            found = conn.execute(
                f"SELECT id{', parent_id' if 'parent_id' in ccols else ', NULL AS parent_id'} FROM companies WHERE uid = ?",
                (uid,),
            ).fetchone()
            if found is not None:
                conn.execute("UPDATE projects SET company_id = NULL WHERE company_id = ?", (found["id"],))
                if "parent_id" in ccols:
                    conn.execute("UPDATE companies SET parent_id = ?, updated_at = ? WHERE parent_id = ?",
                                 (found["parent_id"], stamp, found["id"]))
                conn.execute("DELETE FROM companies WHERE id = ?", (found["id"],))
                report["companies_updated"] += 1
            continue
        if live_seen >= MAX_COMPANIES:
            continue
        live_seen += 1
        name = _text(item.get("name"))
        if name is None:
            continue
        live_items.append(item)
        found = conn.execute("SELECT id, name FROM companies WHERE uid = ?", (uid,)).fetchone()
        if found is None:
            same = conn.execute("SELECT id, uid FROM companies WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
            if same is not None and same["uid"] and same["uid"] != uid:
                report["skipped"].append(["company_name_taken", name])
                continue
            if same is not None:
                conn.execute("UPDATE companies SET uid = ?, updated_at = ? WHERE id = ?", (uid, stamp, same["id"]))
                found = same
            else:
                found = {"id": conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES (?, ?, ?, ?)",
                                            (name, uid, stamp, stamp)).lastrowid, "name": name}
                report["companies_created"] += 1
        elif found["name"] != name:
            if conn.execute("SELECT 1 FROM companies WHERE name = ? COLLATE NOCASE AND id != ?", (name, found["id"])).fetchone():
                report["skipped"].append(["company_name_taken", name])
            else:
                conn.execute("UPDATE companies SET name = ?, updated_at = ? WHERE id = ?", (name, stamp, found["id"]))
                report["companies_updated"] += 1
        ids[uid] = int(found["id"])
        hue = item.get("hue")
        if "hue" in ccols and (hue is None or (isinstance(hue, int) and not isinstance(hue, bool) and 0 <= hue <= 359)):
            conn.execute("UPDATE companies SET hue = ? WHERE id = ? AND hue IS NOT ?", (hue, found["id"], hue))
    if "parent_id" in ccols:
        for item in live_items:
            uid = item.get("uid")
            parent = ids.get(item.get("parent_uid")) if uid in ids else None
            if uid in ids and parent != ids[uid]:
                conn.execute("UPDATE companies SET parent_id = ? WHERE id = ? AND parent_id IS NOT ?", (parent, ids[uid], parent))
    return ids


def _materialize_shadow_project(conn: sqlite3.Connection, pcols: Set[str], *, uid: str, name: str, home_iid: str,
                                host_key: str, company_id: Optional[int], color: Optional[str],
                                short_val: Optional[str], archived: Optional[bool], parent_uid: Optional[str],
                                stamp: str) -> None:
    root = f"peer://{home_iid}/{uid}"
    vals: Dict[str, Any] = {
        "root": root,
        "raw_path": root,
        "display_name": name,
        "source": PROJECT_SOURCE_USER,
        "presence": "unchecked",
        "host_key": host_key,
        "created_at": stamp,
        "updated_at": stamp,
        "uid": uid,
    }
    if "last_opened_at" in pcols:
        vals["last_opened_at"] = stamp
    if "company_id" in pcols:
        vals["company_id"] = company_id
    if "color" in pcols:
        vals["color"] = color
    if "short_description" in pcols:
        vals["short_description"] = short_val
    if "archived_at" in pcols and archived is True:
        vals["archived_at"] = stamp
    if "home_install_id" in pcols:
        vals["home_install_id"] = home_iid
    if "parent_uid" in pcols:
        vals["parent_uid"] = parent_uid
    cols = list(vals)
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(f"INSERT INTO projects ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals[c] for c in cols))


def _update_projects(conn: sqlite3.Connection, rows: Sequence[Any], company_ids: Mapping[str, int],
                     own_install_id: str, report: Dict[str, Any]) -> None:
    pcols = _columns(conn, "projects")
    _host_to_iid, iid_to_host = _peer_host_maps(conn)
    stored_parents = synced_project_parents(conn)
    parents_dirty = False
    pending_parent_uids: List[Tuple[str, Optional[str]]] = []
    stamp = utc_now()
    for item in rows[:MAX_PROJECTS]:
        if not isinstance(item, Mapping):
            continue
        uid = _valid_uid(item.get("uid"))
        if uid is None:
            continue
        row = conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone()
        name = _text(item.get("name"))
        color = item.get("color") if is_hex_color(item.get("color")) else None
        company_id = company_ids.get(item.get("company_uid")) if item.get("company_uid") else None
        short = item.get("short_description") if isinstance(item.get("short_description"), str) else None
        short_val = short[:200] if short else None
        archived = item.get("archived") if isinstance(item.get("archived"), bool) else None
        has_parent_uid = "parent_uid" in item
        raw_parent = _valid_uid(item.get("parent_uid"))
        parent_uid = raw_parent if raw_parent != uid else None
        home_iid = _valid_install_id(item.get("home_iid"))

        if row is None:
            if home_iid is None or home_iid == own_install_id or name is None:
                continue
            host_key = iid_to_host.get(home_iid) or f"peer:{home_iid[:12]}"
            _materialize_shadow_project(
                conn, pcols, uid=uid, name=name, home_iid=home_iid, host_key=host_key,
                company_id=company_id, color=color, short_val=short_val, archived=archived,
                parent_uid=parent_uid, stamp=stamp,
            )
            report["projects_updated"] += 1
            if has_parent_uid and "parent_uid" not in pcols:
                if "parent_project_id" in pcols:
                    pending_parent_uids.append((uid, parent_uid))
                elif parent_uid is not None and stored_parents.get(uid) != parent_uid:
                    stored_parents[uid] = parent_uid
                    parents_dirty = True
            continue

        if item.get("company_uid") and company_id is None:
            company_id = row["company_id"]
        sets: Dict[str, Any] = {"company_id": company_id, "color": color}
        if "short_description" in pcols:
            sets["short_description"] = short_val
        if archived is not None and "archived_at" in pcols:
            if archived and not row["archived_at"]:
                sets["archived_at"] = stamp
            elif not archived and row["archived_at"]:
                sets["archived_at"] = None
        if home_iid is not None and "home_install_id" in pcols and row["host_key"] != LOCAL_HOST_KEY:
            sets["home_install_id"] = home_iid
        if has_parent_uid and "parent_uid" in pcols:
            sets["parent_uid"] = parent_uid
        if name is not None and name != row["display_name"]:
            if row["host_key"] == LOCAL_HOST_KEY and conn.execute(
                "SELECT 1 FROM projects WHERE display_name = ? AND id != ? AND host_key = ?",
                (name, row["id"], LOCAL_HOST_KEY),
            ).fetchone():
                report["skipped"].append(["project_name_taken", name])
            else:
                sets["display_name"] = name
        changed = {k: v for k, v in sets.items() if row[k] != v}
        row_changed = False
        if changed:
            conn.execute(f"UPDATE projects SET {', '.join(k + ' = ?' for k in changed)}, updated_at = ? WHERE id = ?",
                         (*changed.values(), stamp, row["id"]))
            row_changed = True
        if has_parent_uid and "parent_uid" not in pcols:
            if "parent_project_id" in pcols:
                pending_parent_uids.append((uid, parent_uid))
            elif row["host_key"] != LOCAL_HOST_KEY:
                if parent_uid is None:
                    if uid in stored_parents:
                        del stored_parents[uid]
                        parents_dirty = True
                        row_changed = True
                elif stored_parents.get(uid) != parent_uid:
                    stored_parents[uid] = parent_uid
                    parents_dirty = True
                    row_changed = True
        if row_changed:
            report["projects_updated"] += 1

    if "parent_project_id" in pcols and pending_parent_uids:
        uid_to_pid = {r[0]: int(r[1]) for r in conn.execute("SELECT uid, id FROM projects WHERE uid IS NOT NULL")}
        for child_uid, parent_uid in pending_parent_uids:
            child_pid = uid_to_pid.get(child_uid)
            parent_pid = uid_to_pid.get(parent_uid) if parent_uid is not None else None
            if child_pid is None or parent_pid == child_pid:
                continue
            cur = conn.execute("UPDATE projects SET parent_project_id = ?, updated_at = ? WHERE id = ? AND parent_project_id IS NOT ?",
                               (parent_pid, stamp, child_pid, parent_pid))
            if cur.rowcount > 0:
                report["projects_updated"] += 1
    if parents_dirty:
        _save_synced_project_parents(conn, stored_parents)


def doc_pairs(doc: Mapping[str, Any], own_install_id: str, limit: int = 5000) -> Dict[str, List[str]]:
    arr = doc.get("arrangement") if isinstance(doc.get("arrangement"), Mapping) else {}
    bands = arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}
    groups = [g for g in (doc.get("groups") if isinstance(doc.get("groups"), list) else [])[:panel_groups.MAX_GROUPS + panel_groups.MAX_TOMBS] if isinstance(g, Mapping)]
    layouts = [ly for ly in (doc.get("layouts") if isinstance(doc.get("layouts"), list) else [])[:panel_layouts.MAX_LAYOUTS + panel_layouts.MAX_TOMBS] if isinstance(ly, Mapping)]
    lists = [arr.get("pinned"), arr.get("order"), *[bands[k] for k in list(bands)[:2600]],
             *[g.get(f) for g in groups for f in ("members", "band")], *[ly.get("members") for ly in layouts]]
    out: Dict[str, List[str]] = {}
    for pairs in lists:
        for pair in pairs if isinstance(pairs, list) else []:
            if (isinstance(pair, list) and len(pair) >= 2 and isinstance(pair[0], str) and isinstance(pair[1], str)
                    and 0 < len(pair[0]) <= 64 and 0 < len(pair[1]) <= 64 and pair[0] not in (own_install_id, "layout")):
                out[shadow_uuid(pair[0], pair[1])] = [pair[0], pair[1]]
            if len(out) >= limit:
                return out
    return out


def _local_keys(pairs: Any, own_install_id: str) -> List[str]:
    out: List[str] = []
    for pair in pairs if isinstance(pairs, list) else []:
        if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) and 0 < len(x) <= 64 for x in pair):
            if pair[0] == "layout":
                out.append(f"layout:{pair[1]}")
            else:
                out.append(pair[1] if pair[0] == own_install_id else shadow_uuid(pair[0], pair[1]))
    return list(dict.fromkeys(out))[:MAX_REMEMBERED]


def _arrangement(conn: sqlite3.Connection, doc: Mapping[str, Any], current: Optional[Mapping[str, Any]], own_install_id: str,
                 doc_uids: Set[str], group_bands: Mapping[str, Optional[List[List[str]]]] = {}) -> Dict[str, Any]:
    cur = dict(current) if isinstance(current, Mapping) else {}
    arr = doc.get("arrangement") if isinstance(doc.get("arrangement"), Mapping) else {}
    pid_by_uid = {r[1]: r[0] for r in conn.execute("SELECT id, uid FROM projects WHERE uid IS NOT NULL")}
    uid_by_pid = {v: k for k, v in pid_by_uid.items()}
    bands: Dict[str, List[str]] = {}
    for key, members in (arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}).items():
        match = _PROJECT_BAND.fullmatch(key) if isinstance(key, str) else None
        if key in _KIND_BANDS:
            bands[key] = _local_keys(members, own_install_id)
        elif match and match.group(1) in pid_by_uid:
            bands[f"p:{pid_by_uid[match.group(1)]}"] = _local_keys(members, own_install_id)
    for key, members in (cur.get("bands") if isinstance(cur.get("bands"), Mapping) else {}).items():
        if key in bands or key in _KIND_BANDS or (isinstance(key, str) and key.startswith("g:") and key[2:] in group_bands):
            continue
        if key.startswith("p:") and key[2:].isdigit() and uid_by_pid.get(int(key[2:])) in doc_uids:
            continue
        bands[key] = members
    bands.update({f"g:{uid}": _local_keys(pairs, own_install_id) for uid, pairs in group_bands.items() if pairs is not None})
    new = {**cur, "v": cur.get("v", ARRANGEMENT_SCHEMA_VERSION),
           "pinned": _local_keys(arr.get("pinned"), own_install_id),
           "order": _local_keys(arr.get("order"), own_install_id), "bands": bands}
    sections = [s for s in arr.get("sections") or [] if s in SECTION_IDS] if isinstance(arr.get("sections"), list) else None
    if sections:
        new["sections"] = list(dict.fromkeys(sections))
    return new


def apply(conn: sqlite3.Connection, doc: Any, own_install_id: str, current: Optional[Mapping[str, Any]],
          group_stamps: Optional[Mapping[str, Any]] = None,
          layout_stamps: Optional[Mapping[str, Any]] = None) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    report: Dict[str, Any] = {"companies_created": 0, "companies_updated": 0, "projects_updated": 0, "groups_changed": 0, "layouts_changed": 0, "skipped": []}
    if not isinstance(doc, Mapping) or doc.get("v") != VERSION:
        return report, None
    companies = doc.get("companies") if isinstance(doc.get("companies"), list) else []
    projects = doc.get("projects") if isinstance(doc.get("projects"), list) else []
    ids = _upsert_companies(conn, companies, report)
    _update_projects(conn, projects, ids, own_install_id, report)
    doc_uids = {p["uid"] for p in projects[:MAX_PROJECTS] if isinstance(p, Mapping) and isinstance(p.get("uid"), str)}
    arr = doc.get("arrangement") if isinstance(doc.get("arrangement"), Mapping) else {}
    panel_layouts.apply(
        conn,
        doc.get("layouts"),
        arr.get("layout_order"),
        lambda origin_iid, origin_suuid: origin_suuid if origin_iid == own_install_id else shadow_uuid(origin_iid, origin_suuid),
        report,
        layout_stamps,
    )
    group_bands = panel_groups.apply(conn, doc.get("groups"), arr.get("group_order"), lambda pairs: _local_keys(pairs, own_install_id), report, group_stamps)
    return report, _arrangement(conn, doc, current, own_install_id, doc_uids, group_bands)
