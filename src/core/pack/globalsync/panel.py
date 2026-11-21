
from __future__ import annotations

import re
import sqlite3
from typing import Any, Collection, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import structlog

from src.core.federation.shadow_rows import shadow_uuid
from src.core.pack.globalsync import panel_groups
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.project_colors.palette import is_hex_color
from src.core.trail_entry import utc_now
from src.core.ui_preferences.constants import ARRANGEMENT_SCHEMA_VERSION, MAX_REMEMBERED
from src.core.ui_preferences.drawer_arrangement import SECTION_IDS

logger = structlog.get_logger()

VERSION = 1
CAP = "pack.global_setup.panel"
MAX_COMPANIES, MAX_PROJECTS, MAX_NAME = 500, 2000, 200
_UID = re.compile(r"[0-9a-f]{32}")
_PROJECT_BAND = re.compile(r"p:([0-9a-f]{32})")
_KIND_BANDS = frozenset({"rogue", "terminals", "browsers", "files", "review"})
_ARRANGEMENT_KEYS = ("pinned", "order", "bands", "sections")


def _columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


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
            extra_keys: Optional[Mapping[str, Sequence[str]]] = None, known_groups: Collection[str] = ()) -> Dict[str, Any]:
    ccols = _columns(conn, "companies")
    cid_uid = {r[0]: r[1] for r in conn.execute("SELECT id, uid FROM companies WHERE uid IS NOT NULL")}
    companies = [{"uid": r["uid"], "name": r["name"], "parent_uid": cid_uid.get(r["parent_id"]) if "parent_id" in ccols else None,
                  "hue": r["hue"] if "hue" in ccols else None}
                 for r in conn.execute(f"SELECT uid, name, {'parent_id' if 'parent_id' in ccols else 'NULL AS parent_id'}, "
                                       f"{'hue' if 'hue' in ccols else 'NULL AS hue'} FROM companies WHERE uid IS NOT NULL ORDER BY id")]
    pcols = _columns(conn, "projects")
    short = "short_description" if "short_description" in pcols else "NULL AS short_description"
    rows = [r for r in conn.execute(f"SELECT id, uid, display_name, company_id, color, host_key, {short} FROM projects "
                                    f"WHERE uid IS NOT NULL ORDER BY id") if all_projects or r["host_key"] == LOCAL_HOST_KEY or r["uid"] in stamped_uids]
    projects = [{"uid": r["uid"], "name": r["display_name"], "company_uid": cid_uid.get(r["company_id"]), "color": r["color"],
                 "short_description": r["short_description"]} for r in rows]
    pid_uid = {r[0]: r[1] for r in conn.execute("SELECT id, uid FROM projects WHERE uid IS NOT NULL")}
    keys = {**{k: list(v) for k, v in (extra_keys or {}).items()}, **_session_keys(conn, own_install_id)}
    arr = arrangement if isinstance(arrangement, Mapping) else {}

    def portable(uuids: Any) -> List[List[str]]:
        return [keys[u] for u in (uuids if isinstance(uuids, list) else []) if isinstance(u, str) and u in keys]

    bands: Dict[str, List[List[str]]] = {}
    for key, members in (arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}).items():
        if key in _KIND_BANDS:
            bands[key] = portable(members)
        elif isinstance(key, str) and key.startswith("p:") and key[2:].isdigit() and int(key[2:]) in pid_uid:
            bands[f"p:{pid_uid[int(key[2:])]}"] = portable(members)
    sections = arr.get("sections") if isinstance(arr.get("sections"), list) else None
    groups, group_order = panel_groups.collect(conn, portable, arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}, known_groups)
    return {"v": VERSION, "companies": companies, "projects": projects, "groups": groups,
            "arrangement": {"group_order": group_order, "pinned": portable([p for p in arr.get("pinned") or [] if isinstance(p, str) and not p.startswith("layout:")]),
                            "order": portable(arr.get("order")), "bands": bands, "sections": sections}}


def _text(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= MAX_NAME else None


def _upsert_companies(conn: sqlite3.Connection, rows: Sequence[Any], report: Dict[str, Any]) -> Dict[str, int]:
    ccols = _columns(conn, "companies")
    ids: Dict[str, int] = {}
    stamp = utc_now()
    for item in rows[:MAX_COMPANIES]:
        uid, name = (item.get("uid") if isinstance(item, Mapping) else None), _text(item.get("name") if isinstance(item, Mapping) else None)
        if not isinstance(uid, str) or not _UID.fullmatch(uid) or name is None:
            continue
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
        for item in rows[:MAX_COMPANIES]:
            uid = item.get("uid") if isinstance(item, Mapping) else None
            parent = ids.get(item.get("parent_uid")) if isinstance(item, Mapping) and uid in ids else None
            if uid in ids and parent != ids[uid]:
                conn.execute("UPDATE companies SET parent_id = ? WHERE id = ? AND parent_id IS NOT ?", (parent, ids[uid], parent))
    return ids


def _update_projects(conn: sqlite3.Connection, rows: Sequence[Any], company_ids: Mapping[str, int], report: Dict[str, Any]) -> None:
    pcols = _columns(conn, "projects")
    stamp = utc_now()
    for item in rows[:MAX_PROJECTS]:
        if not isinstance(item, Mapping) or not isinstance(item.get("uid"), str):
            continue
        row = conn.execute("SELECT * FROM projects WHERE uid = ?", (item["uid"],)).fetchone()
        if row is None:
            continue
        name = _text(item.get("name"))
        color = item.get("color") if is_hex_color(item.get("color")) else None
        company_id = company_ids.get(item.get("company_uid")) if item.get("company_uid") else None
        if item.get("company_uid") and company_id is None:
            company_id = row["company_id"]
        short = item.get("short_description") if isinstance(item.get("short_description"), str) else None
        sets: Dict[str, Any] = {"company_id": company_id, "color": color}
        if "short_description" in pcols:
            sets["short_description"] = short[:200] if short else None
        if name is not None and name != row["display_name"]:
            if conn.execute("SELECT 1 FROM projects WHERE display_name = ? AND id != ? AND host_key = ?", (name, row["id"], LOCAL_HOST_KEY)).fetchone():
                report["skipped"].append(["project_name_taken", name])
            else:
                sets["display_name"] = name
        changed = {k: v for k, v in sets.items() if row[k] != v}
        if changed:
            conn.execute(f"UPDATE projects SET {', '.join(k + ' = ?' for k in changed)}, updated_at = ? WHERE id = ?",
                         (*changed.values(), stamp, row["id"]))
            report["projects_updated"] += 1


def doc_pairs(doc: Mapping[str, Any], own_install_id: str, limit: int = 5000) -> Dict[str, List[str]]:
    arr = doc.get("arrangement") if isinstance(doc.get("arrangement"), Mapping) else {}
    bands = arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}
    groups = [g for g in (doc.get("groups") if isinstance(doc.get("groups"), list) else [])[:panel_groups.MAX_GROUPS + panel_groups.MAX_TOMBS] if isinstance(g, Mapping)]
    lists = [arr.get("pinned"), arr.get("order"), *[bands[k] for k in list(bands)[:2600]], *[g.get(f) for g in groups for f in ("members", "band")]]
    out: Dict[str, List[str]] = {}
    for pairs in lists:
        for pair in pairs if isinstance(pairs, list) else []:
            if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) and 0 < len(x) <= 64 for x in pair) and pair[0] != own_install_id:
                out[shadow_uuid(pair[0], pair[1])] = [pair[0], pair[1]]
            if len(out) >= limit:
                return out
    return out


def _local_keys(pairs: Any, own_install_id: str) -> List[str]:
    out: List[str] = []
    for pair in pairs if isinstance(pairs, list) else []:
        if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) and 0 < len(x) <= 64 for x in pair):
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
    own_layouts = [p for p in cur.get("pinned") or [] if isinstance(p, str) and p.startswith("layout:")]
    new = {**cur, "v": cur.get("v", ARRANGEMENT_SCHEMA_VERSION),
           "pinned": (_local_keys(arr.get("pinned"), own_install_id) + own_layouts)[:MAX_REMEMBERED],
           "order": _local_keys(arr.get("order"), own_install_id), "bands": bands}
    sections = [s for s in arr.get("sections") or [] if s in SECTION_IDS] if isinstance(arr.get("sections"), list) else None
    if sections:
        new["sections"] = list(dict.fromkeys(sections))
    return new


def apply(conn: sqlite3.Connection, doc: Any, own_install_id: str, current: Optional[Mapping[str, Any]],
          group_stamps: Optional[Mapping[str, Any]] = None) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    report: Dict[str, Any] = {"companies_created": 0, "companies_updated": 0, "projects_updated": 0, "groups_changed": 0, "skipped": []}
    if not isinstance(doc, Mapping) or doc.get("v") != VERSION:
        return report, None
    companies = doc.get("companies") if isinstance(doc.get("companies"), list) else []
    projects = doc.get("projects") if isinstance(doc.get("projects"), list) else []
    ids = _upsert_companies(conn, companies, report)
    _update_projects(conn, projects, ids, report)
    doc_uids = {p["uid"] for p in projects[:MAX_PROJECTS] if isinstance(p, Mapping) and isinstance(p.get("uid"), str)}
    arr = doc.get("arrangement") if isinstance(doc.get("arrangement"), Mapping) else {}
    group_bands = panel_groups.apply(conn, doc.get("groups"), arr.get("group_order"), lambda pairs: _local_keys(pairs, own_install_id), report, group_stamps)
    return report, _arrangement(conn, doc, current, own_install_id, doc_uids, group_bands)
