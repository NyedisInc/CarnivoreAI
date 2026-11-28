
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Collection, Dict, List, Mapping, Optional, Set, Tuple, Union

from src.core.json_artifact import atomic_write_json
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.pack.globalsync import panel, panel_groups, panel_layouts

LOCK = threading.RLock()
MAX_SKEW_MS = 5 * 60 * 1000
MAX_KEY, MAX_BANDS = 300, 2600
_GROUP_FIELDS = ("name", "members", "band", "parent_key", "style", "icon", "rule", "gone")
_GROUP_OPTIONAL_FIELDS = frozenset({"parent_key", "style", "icon", "rule"})
_LAYOUT_FIELDS = ("name", "shape", "style", "members", "gone")
_COMPANY_FIELDS = ("name", "parent_uid", "hue", "gone")
_PROJECT_FIELDS = ("name", "company_uid", "color", "short_description", "archived", "parent_uid", "home_iid")
Stamp = Tuple[int, str]


def now_ms() -> int:
    return int(time.time() * 1000)


def _hash(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


class Ledger:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.fields: Dict[str, List[Any]] = {}
        self.pending = False
        self.init = False
        self.known: Dict[str, List[str]] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        rows = raw.get("fields") if isinstance(raw, dict) else None
        if not isinstance(rows, dict):
            return
        self.fields = {k: v for k, v in rows.items() if isinstance(k, str) and isinstance(v, list) and len(v) == 3
                       and isinstance(v[0], int) and isinstance(v[1], str) and isinstance(v[2], str)}
        self.pending, self.init = raw.get("pending") is True, raw.get("init") is True
        known = raw.get("known")
        self.known = {k: v for k, v in (known.items() if isinstance(known, dict) else []) if isinstance(k, str) and isinstance(v, list)
                      and len(v) == 2 and all(isinstance(x, str) for x in v)}

    def stamp(self, key: str) -> Stamp:
        row = self.fields.get(key)
        return (row[0], row[1]) if row else (0, "")

    def save(self) -> None:
        atomic_write_json(self.path, {"v": 1, "init": self.init, "pending": self.pending, "fields": self.fields, "known": self.known},
                          log_event="pack_panel_stamps_write_failed")

    def stamped_project_uids(self) -> Set[str]:
        return {k.split(":")[1] for k, v in self.fields.items() if k.startswith("p:") and v[0] > 0}

    def known_groups(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        gone_true = _hash(True)
        for key, row in self.fields.items():
            if key.startswith("g:"):
                uid = key.split(":")[1]
                out.setdefault(uid, 0)
                if key.endswith(":gone"):
                    out[uid] = row[0] if row[2] == gone_true else 1 << 62
        return out

    def known_companies(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        gone_true = _hash(True)
        for key, row in self.fields.items():
            if key.startswith("c:"):
                uid = key.split(":")[1]
                out.setdefault(uid, 0)
                if key.endswith(":gone"):
                    out[uid] = row[0] if row[2] == gone_true else 1 << 62
        return out

    def known_layouts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        gone_true = _hash(True)
        for key, row in self.fields.items():
            if key.startswith("ly:"):
                uid = key.split(":")[1]
                out.setdefault(uid, 0)
                if key.endswith(":gone"):
                    out[uid] = row[0] if row[2] == gone_true else 1 << 62
        return out

    def stamps_for(self, keys: Any) -> Dict[str, List[Any]]:
        return {k: [self.fields[k][0], self.fields[k][1]] for k in keys if k in self.fields and self.fields[k][0] > 0}


def flatten(doc: Mapping[str, Any]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    live_c = gone_c = 0
    for item in (doc.get("companies") if isinstance(doc.get("companies"), list) else [])[:panel.MAX_COMPANIES + panel.MAX_COMPANY_TOMBS]:
        if isinstance(item, Mapping) and isinstance(item.get("uid"), str) and panel._UID.fullmatch(item["uid"]):
            if item.get("gone") is True:
                gone_c += 1
            else:
                live_c += 1
            if live_c > panel.MAX_COMPANIES or gone_c > panel.MAX_COMPANY_TOMBS:
                continue
            for name in _COMPANY_FIELDS:
                flat[f"c:{item['uid']}:{name}"] = item.get(name) is True if name == "gone" else item.get(name)
    for item in (doc.get("projects") if isinstance(doc.get("projects"), list) else [])[:panel.MAX_PROJECTS]:
        if isinstance(item, Mapping) and isinstance(item.get("uid"), str) and panel._UID.fullmatch(item["uid"]):
            for name in _PROJECT_FIELDS:
                flat[f"p:{item['uid']}:{name}"] = item.get(name)
    live = gone = 0
    for item in (doc.get("groups") if isinstance(doc.get("groups"), list) else [])[:panel_groups.MAX_GROUPS + panel_groups.MAX_TOMBS]:
        if isinstance(item, Mapping) and isinstance(item.get("uid"), str) and panel_groups.UID.fullmatch(item["uid"]):
            if item.get("gone") is True:
                gone += 1
            else:
                live += 1
            if live > panel_groups.MAX_GROUPS or gone > panel_groups.MAX_TOMBS:
                continue
            for name in _GROUP_FIELDS:
                if name in _GROUP_OPTIONAL_FIELDS and name not in item:
                    continue
                flat[f"g:{item['uid']}:{name}"] = item.get(name) is True if name == "gone" else item.get(name)
    live_ly = gone_ly = 0
    for item in (doc.get("layouts") if isinstance(doc.get("layouts"), list) else [])[:panel_layouts.MAX_LAYOUTS + panel_layouts.MAX_TOMBS]:
        if isinstance(item, Mapping) and isinstance(item.get("uid"), str) and panel_layouts.UID.fullmatch(item["uid"]):
            if item.get("gone") is True:
                gone_ly += 1
            else:
                live_ly += 1
            if live_ly > panel_layouts.MAX_LAYOUTS or gone_ly > panel_layouts.MAX_TOMBS:
                continue
            for name in _LAYOUT_FIELDS:
                flat[f"ly:{item['uid']}:{name}"] = item.get(name) is True if name == "gone" else item.get(name)
    arr = doc.get("arrangement") if isinstance(doc.get("arrangement"), Mapping) else {}
    for name in ("pinned", "order", "sections", "group_order", "layout_order"):
        if name == "layout_order" and name not in arr:
            continue
        flat[f"a:{name}"] = arr.get(name)
    bands = arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}
    for key in list(bands)[:MAX_BANDS]:
        if isinstance(key, str) and len(key) <= 64:
            flat[f"a:band:{key}"] = bands[key]
    return flat


def unflatten(flat: Mapping[str, Any]) -> Dict[str, Any]:
    companies: Dict[str, Dict[str, Any]] = {}
    projects: Dict[str, Dict[str, Any]] = {}
    groups: Dict[str, Dict[str, Any]] = {}
    layouts: Dict[str, Dict[str, Any]] = {}
    arr: Dict[str, Any] = {}
    bands: Dict[str, Any] = {}
    for key, value in flat.items():
        kind, _, rest = key.partition(":")
        if kind in ("c", "p", "g", "ly"):
            uid, _, name = rest.partition(":")
            {"c": companies, "p": projects, "g": groups, "ly": layouts}[kind].setdefault(uid, {"uid": uid})[name] = value
        elif rest.startswith("band:"):
            bands[rest[5:]] = value
        else:
            arr[rest] = value
    return {"v": panel.VERSION, "companies": list(companies.values()), "projects": list(projects.values()),
            "groups": list(groups.values()), "layouts": list(layouts.values()), "arrangement": {**arr, "bands": bands}}


def clean_stamps(raw: Any, now: int) -> Dict[str, Stamp]:
    out: Dict[str, Stamp] = {}
    for key, row in (raw.items() if isinstance(raw, Mapping) else []):
        if (isinstance(key, str) and len(key) <= MAX_KEY and isinstance(row, list) and len(row) == 2 and isinstance(row[0], int)
                and not isinstance(row[0], bool) and row[0] > 0 and isinstance(row[1], str) and len(row[1]) <= 64):
            out[key] = (min(row[0], now + MAX_SKEW_MS), row[1])
        if len(out) >= MAX_PROJECTS_FIELDS:
            break
    return out


MAX_PROJECTS_FIELDS = (
    (panel.MAX_PROJECTS * len(_PROJECT_FIELDS))
    + ((panel.MAX_COMPANIES + panel.MAX_COMPANY_TOMBS) * len(_COMPANY_FIELDS))
    + MAX_BANDS
    + ((panel_groups.MAX_GROUPS + panel_groups.MAX_TOMBS) * len(_GROUP_FIELDS))
    + ((panel_layouts.MAX_LAYOUTS + panel_layouts.MAX_TOMBS) * len(_LAYOUT_FIELDS))
    + 16
)


def local_doc(conn: sqlite3.Connection, arrangement: Optional[Mapping[str, Any]], own_iid: str, ledger: Ledger, member: bool = False) -> Dict[str, Any]:
    return panel.collect(conn, arrangement, own_iid, stamped_uids=ledger.stamped_project_uids(), all_projects=member, extra_keys=ledger.known,
                         known_groups=ledger.known_groups(), known_companies=ledger.known_companies(), known_layouts=ledger.known_layouts())


def shadow_uids(conn: sqlite3.Connection) -> Set[str]:
    return {r[0] for r in conn.execute("SELECT uid FROM projects WHERE uid IS NOT NULL AND host_key != ?", (LOCAL_HOST_KEY,))}


def observe(ledger: Ledger, flat: Mapping[str, Any], own_iid: str, now: int, quiet: Collection[str] = ()) -> int:
    baseline, changed, fresh = not ledger.init, 0, {}
    for key, value in flat.items():
        digest, old = _hash(value), ledger.fields.get(key)
        if old is None:
            hush = baseline or (key.startswith("p:") and key.split(":")[1] in quiet)
            fresh[key] = [0, "", digest] if hush else [now, own_iid, digest]
            changed += 0 if hush else 1
        elif old[2] != digest:
            fresh[key] = [max(now, old[0] + 1), own_iid, digest]
            changed += 1
        else:
            fresh[key] = old
    ledger.fields, ledger.init = fresh, True
    if changed:
        ledger.pending = True
    return changed


def merge(local_flat: Mapping[str, Any], incoming: Mapping[str, Any], ledger: Ledger, *, from_main: bool, now: int) -> Tuple[Dict[str, Any], Dict[str, Stamp]]:
    theirs_all = clean_stamps(incoming.get("stamps"), now)
    incoming_flat = flatten(incoming)
    merged, won = dict(local_flat), {}
    edited = {k.split(":")[1] for k in theirs_all if k.startswith("p:")}
    incoming_home = {k.split(":")[1] for k, v in incoming_flat.items() if k.startswith("p:") and k.endswith(":home_iid") and isinstance(v, str) and v}
    for key, value in incoming_flat.items():
        mine, theirs = ledger.stamp(key), theirs_all.get(key, (0, ""))
        newer = theirs > mine or (theirs == mine and from_main)
        if key.startswith("p:") and key not in local_flat:
            puid = key.split(":")[1]
            if puid not in edited and not (from_main and puid in incoming_home):
                continue
        if key not in local_flat or (newer and _hash(value) != _hash(local_flat[key])):
            merged[key], won[key] = value, theirs
        elif theirs > mine:
            won[key] = theirs
    return merged, won


def adopt(conn: sqlite3.Connection, ledger: Ledger, arrangement: Optional[Mapping[str, Any]], own_iid: str, won: Mapping[str, Stamp],
          member: bool = False, arrangement_only: bool = False) -> None:
    stamped = ledger.stamped_project_uids() | {k.split(":")[1] for k, s in won.items() if k.startswith("p:") and s[0] > 0}
    after = flatten(panel.collect(conn, arrangement, own_iid, stamped_uids=stamped, all_projects=member, extra_keys=ledger.known,
                                     known_groups=ledger.known_groups(), known_companies=ledger.known_companies(), known_layouts=ledger.known_layouts()))
    fresh = {}
    for key, value in after.items():
        old = ledger.fields.get(key)
        if arrangement_only and not (key.startswith("a:") or (key.startswith("g:") and key.endswith(":band"))):
            if old is not None:
                fresh[key] = old
            continue
        stamp = won.get(key) or ((old[0], old[1]) if old else (0, ""))
        fresh[key] = [stamp[0], stamp[1], _hash(value)]
    ledger.fields = fresh
    arr = arrangement if isinstance(arrangement, Mapping) else {}
    listed = set(arr.get("pinned") or []) | set(arr.get("order") or [])
    for members in (arr.get("bands") if isinstance(arr.get("bands"), Mapping) else {}).values():
        listed |= set(members) if isinstance(members, list) else set()
    listed |= panel_groups.member_keys(conn) | panel_layouts.member_keys(conn)
    ledger.known = {k: v for k, v in ledger.known.items() if k in listed}


def receive(conn: sqlite3.Connection, doc: Any, own_iid: str, current: Optional[Mapping[str, Any]], ledger_path: Path, *,
            from_main: bool) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if not isinstance(doc, Mapping) or doc.get("v") != panel.VERSION:
        return panel.apply(conn, doc, own_iid, current)
    now = now_ms()
    with LOCK:
        ledger = Ledger(ledger_path)
        member = from_main
        mine = flatten(local_doc(conn, current, own_iid, ledger, member))
        observe(ledger, mine, own_iid, now, shadow_uids(conn))
        merged, won = merge(mine, doc, ledger, from_main=from_main, now=now)
        group_stamps = {k.split(":")[1]: won.get(k) or ledger.stamp(k) for k in merged if k.startswith("g:") and k.endswith(":members")}
        layout_stamps = {k.split(":")[1]: won.get(k) or ledger.stamp(k) for k in merged if k.startswith("ly:") and k.endswith(":members")}
        report, new = panel.apply(conn, unflatten(merged), own_install_id=own_iid, current=current, group_stamps=group_stamps, layout_stamps=layout_stamps)
        ledger.known.update(panel.doc_pairs(unflatten(merged), own_iid))
        adopt(conn, ledger, new, own_iid, won, member)
        ledger.save()
    return report, new


def doc_for_send(conn: sqlite3.Connection, arrangement: Union[Optional[Mapping[str, Any]], Any], own_iid: str, ledger_path: Path,
                 member: bool = False) -> Dict[str, Any]:
    with LOCK:
        ledger = Ledger(ledger_path)
        doc = local_doc(conn, arrangement() if callable(arrangement) else arrangement, own_iid, ledger, member)
        flat = flatten(doc)
        observe(ledger, flat, own_iid, now_ms(), shadow_uids(conn))
        ledger.save()
        return {**doc, "stamps": ledger.stamps_for(flat)}


def rebaseline(conn: sqlite3.Connection, arrangement: Optional[Mapping[str, Any]], own_iid: str, ledger_path: Path, member: bool = False) -> None:
    with LOCK:
        ledger = Ledger(ledger_path)
        adopt(conn, ledger, arrangement, own_iid, {}, member, arrangement_only=True)
        ledger.init = True
        ledger.save()


def pending(ledger_path: Path) -> bool:
    with LOCK:
        return Ledger(ledger_path).pending


def clear_pending(ledger_path: Path) -> None:
    with LOCK:
        ledger = Ledger(ledger_path)
        if ledger.pending:
            ledger.pending = False
            ledger.save()
