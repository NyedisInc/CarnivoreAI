
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Collection, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from src.core.federation.shadow_rows import shadow_uuid
from src.core.pack.globalsync import panel, panel_layouts, panel_merge
from src.core.pack.meshdata import hlc, panel_kind

Scalars = Dict[str, Any]
Lists = Dict[str, List[str]]
BcMap = Dict[str, Dict[str, bool]]
Rows = Mapping[str, Tuple[Any, hlc.Stamp]]
NO_STAMP = hlc.Stamp(0, 0, "")
_PROBE = {"pos": "V"}


def value_hash(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def item_pair(item: str) -> List[str]:
    head, _, tail = item.partition("/")
    if head == "ly":
        return ["layout", tail]
    return [head, tail]


def item_ok(list_id: str, item: str) -> bool:
    return panel_kind.valid(f"l:{list_id}:{item}", _PROBE)


_PROJECT_FIELDS = ("name", "company_uid", "color", "short_description", "archived", "parent_uid", "home_iid")
_COMPANY_FIELDS = ("name", "parent_uid", "hue")
_GROUP_OPT_FIELDS = ("parent_key", "style", "icon", "rule")
_LAYOUT_FIELDS = ("name", "shape", "style")


def local_doc(
    conn: sqlite3.Connection,
    arrangement: Optional[Mapping[str, Any]],
    own_iid: str,
    extra_items: Iterable[str],
    known_groups: Mapping[str, int],
    known_companies: Mapping[str, int] = {},
    known_layouts: Mapping[str, int] = {},
) -> Dict[str, Any]:
    extra = {
        shadow_uuid(i, u): [i, u]
        for i, u in (item_pair(it) for it in extra_items)
        if u and i != "layout"
    }
    return panel.collect(
        conn,
        arrangement,
        own_iid,
        all_projects=True,
        extra_keys=extra,
        known_groups=known_groups,
        known_companies=known_companies,
        known_layouts=known_layouts,
    )


def _item_str(entry: Any, grouped: bool) -> Optional[str]:
    if not grouped:
        return entry if isinstance(entry, str) else None
    if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str) and isinstance(entry[1], str):
        if entry[0] == "layout":
            return f"ly/{entry[1]}"
        return f"{entry[0]}/{entry[1]}"
    return entry if isinstance(entry, str) else None


def _items(pairs: Any, grouped: bool = True) -> List[str]:
    raw = [_item_str(p, grouped) for p in (pairs if isinstance(pairs, list) else [])]
    return list(dict.fromkeys(i for i in raw if isinstance(i, str)))


def layout_member_bc(doc: Mapping[str, Any]) -> BcMap:
    out: BcMap = {}
    for ly in (doc.get("layouts") if isinstance(doc.get("layouts"), list) else []):
        if not isinstance(ly, Mapping) or ly.get("gone") is True or not isinstance(ly.get("uid"), str):
            continue
        lid = f"lm.{ly['uid']}"
        bc_for: Dict[str, bool] = {}
        for entry in ly.get("members") if isinstance(ly.get("members"), list) else []:
            if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str) and isinstance(entry[1], str):
                item = f"{entry[0]}/{entry[1]}"
                bc_for[item] = entry[2] if len(entry) >= 3 and isinstance(entry[2], bool) else True
        if bc_for:
            out[lid] = bc_for
    return out


def flatten_doc(doc: Mapping[str, Any]) -> Tuple[Scalars, Lists]:
    scalars: Scalars = {}
    lists: Lists = {}
    live_c = gone_c = 0
    for c in doc["companies"]:
        if c.get("gone") is True:
            if gone_c < panel.MAX_COMPANY_TOMBS:
                scalars[f"c:{c['uid']}:gone"] = True
                gone_c += 1
            continue
        if live_c >= panel.MAX_COMPANIES:
            continue
        live_c += 1
        for field in _COMPANY_FIELDS:
            scalars[f"c:{c['uid']}:{field}"] = c.get(field)
        scalars[f"c:{c['uid']}:gone"] = False
    for p in doc["projects"][:panel.MAX_PROJECTS]:
        for field in _PROJECT_FIELDS:
            scalars[f"p:{p['uid']}:{field}"] = p.get(field)
    for g in doc["groups"]:
        if g.get("gone") is True:
            scalars[f"g:{g['uid']}:gone"] = True
            continue
        scalars[f"g:{g['uid']}:name"], scalars[f"g:{g['uid']}:gone"] = g.get("name"), False
        for field in _GROUP_OPT_FIELDS:
            if field in g:
                scalars[f"g:{g['uid']}:{field}"] = g[field]
        lists[f"gm.{g['uid']}"] = _items(g.get("members"))
        if g.get("band") is not None:
            lists[f"gb.{g['uid']}"] = _items(g.get("band"))
    live_ly = gone_ly = 0
    for ly in (doc.get("layouts") if isinstance(doc.get("layouts"), list) else []):
        if ly.get("gone") is True:
            if gone_ly < panel_layouts.MAX_TOMBS:
                scalars[f"ly:{ly['uid']}:gone"] = True
                gone_ly += 1
            continue
        if live_ly >= panel_layouts.MAX_LAYOUTS:
            continue
        live_ly += 1
        for field in _LAYOUT_FIELDS:
            scalars[f"ly:{ly['uid']}:{field}"] = ly.get(field)
        scalars[f"ly:{ly['uid']}:gone"] = False
        lists[f"lm.{ly['uid']}"] = _items(ly.get("members"))
    arr = doc["arrangement"]
    scalars["a:sections"] = arr.get("sections")
    lists["pin"], lists["ord"] = _items(arr.get("pinned")), _items(arr.get("order"))
    lists["go"] = _items(arr.get("group_order"), grouped=False)
    if "layout_order" in arr:
        lists["lo"] = _items(arr.get("layout_order"), grouped=False)
    for key, pairs in (arr.get("bands") or {}).items():
        lists[f"b.p.{key[2:]}" if key.startswith("p:") else f"b.{key}"] = _items(pairs)
    return scalars, lists


LEGACY_LISTS = {"pin": "a:pinned", "ord": "a:order", "go": "a:group_order", "lo": "a:layout_order"}


def legacy_field(key: str) -> str:
    if not key.startswith("l:"):
        return key
    list_id = key.split(":", 2)[1]
    if list_id in LEGACY_LISTS:
        return LEGACY_LISTS[list_id]
    kind, _, rest = list_id.partition(".")
    if kind == "b":
        return f"a:band:p:{rest[2:]}" if rest.startswith("p.") else f"a:band:{rest}"
    if kind == "lm":
        return f"ly:{rest}:members"
    return f"g:{rest}:{'members' if kind == 'gm' else 'band'}"


def legacy_hashes(doc: Mapping[str, Any]) -> Dict[str, str]:
    return {k: value_hash(v) for k, v in panel_merge.flatten(doc).items()}


def split_rows(rows: Rows) -> Tuple[Dict[str, Tuple[Any, hlc.Stamp]], Dict[str, Dict[str, Tuple[Optional[str], hlc.Stamp]]]]:
    scalars: Dict[str, Tuple[Any, hlc.Stamp]] = {}
    lists: Dict[str, Dict[str, Tuple[Optional[str], hlc.Stamp]]] = {}
    for key, (value, stamp) in rows.items():
        if key.startswith("l:"):
            _, list_id, item = key.split(":", 2)
            lists.setdefault(list_id, {})[item] = (value.get("pos") if isinstance(value, dict) else None, stamp)
        else:
            scalars[key] = (value, stamp)
    return scalars, lists


def split_row_bc(rows: Rows) -> BcMap:
    out: BcMap = {}
    for key, (value, _stamp) in rows.items():
        if key.startswith("l:lm.") and isinstance(value, dict) and value.get("pos") is not None:
            _, list_id, item = key.split(":", 2)
            out.setdefault(list_id, {})[item] = bool(value.get("bc", True))
    return out


def lis_keep(positions: List[Optional[str]]) -> Set[int]:
    import bisect

    tails: List[str] = []
    tail_at: List[int] = []
    back: Dict[int, Optional[int]] = {}
    for i, pos in enumerate(positions):
        if pos is None:
            continue
        j = bisect.bisect_left(tails, pos)
        if j == len(tails):
            tails.append(pos)
            tail_at.append(i)
        else:
            tails[j], tail_at[j] = pos, i
        back[i] = tail_at[j - 1] if j else None
    keep: Set[int] = set()
    cur = tail_at[-1] if tail_at else None
    while cur is not None:
        keep.add(cur)
        cur = back[cur]
    return keep


def _stamp_of(rec: Mapping[str, Tuple[Optional[str], hlc.Stamp]], item: str) -> hlc.Stamp:
    return rec[item][1] if item in rec else NO_STAMP


def _list_items(list_id: str, local: Lists, store: Mapping[str, Mapping[str, Tuple[Optional[str], hlc.Stamp]]]) -> List[str]:
    rec = store.get(list_id, {})
    live = sorted((pos, item) for item, (pos, _s) in rec.items() if pos is not None)
    return [item for _p, item in live] + [i for i in local.get(list_id, []) if i not in rec]


def _single_home(prefix: str, ids: Collection[str], items: Dict[str, List[str]], store: Mapping[str, Mapping[str, Tuple[Optional[str], hlc.Stamp]]]) -> None:
    best: Dict[str, Tuple[hlc.Stamp, str]] = {}
    for lid in ids:
        if lid.startswith(prefix):
            for item in items[lid]:
                rank = (_stamp_of(store.get(lid, {}), item), lid)
                if item not in best or rank > best[item]:
                    best[item] = rank
    for lid in ids:
        if lid.startswith(prefix):
            items[lid] = [i for i in items[lid] if best[i][1] == lid]


def build_doc(
    scalars: Scalars,
    lists: Lists,
    rows: Rows,
    held_back: Collection[str] = (),
    local_bc: Optional[Mapping[str, Mapping[str, bool]]] = None,
) -> Dict[str, Any]:
    store_s, store_l = split_rows(rows)
    store_bc = split_row_bc(rows)
    merged: Scalars = {**scalars, **{k: v for k, (v, _s) in store_s.items() if k not in held_back}}

    def uids(prefix: str) -> List[str]:
        return list(dict.fromkeys(k.split(":")[1] for k in scalars if k.startswith(prefix)))

    local_c = uids("c:")
    only_c = sorted({k.split(":")[1] for k in store_s if k.startswith("c:")} - set(local_c),
                    key=lambda u: (min(s for k, (_v, s) in store_s.items() if k.startswith(f"c:{u}:")), u))
    live_companies: List[Dict[str, Any]] = []
    gone_companies: List[Dict[str, Any]] = []
    for u in local_c + only_c:
        if merged.get(f"c:{u}:gone") is True:
            if len(gone_companies) < panel.MAX_COMPANY_TOMBS:
                gone_companies.append({"uid": u, "name": None, "parent_uid": None, "hue": None, "gone": True})
            continue
        if len(live_companies) < panel.MAX_COMPANIES:
            live_companies.append({"uid": u, **{f: merged.get(f"c:{u}:{f}") for f in _COMPANY_FIELDS}, "gone": False})
    companies = live_companies + gone_companies

    local_p = uids("p:")
    only_p = sorted({k.split(":")[1] for k in store_s if k.startswith("p:")} - set(local_p),
                    key=lambda u: (min(s for k, (_v, s) in store_s.items() if k.startswith(f"p:{u}:")), u))
    projects = [{"uid": u, **{f: merged.get(f"p:{u}:{f}") for f in _PROJECT_FIELDS}} for u in (local_p + only_p)[:panel.MAX_PROJECTS]]
    ids = sorted(set(lists) | set(store_l))
    items = {lid: _list_items(lid, lists, store_l) for lid in ids}
    _single_home("b.", ids, items, store_l)
    _single_home("gm.", ids, items, store_l)
    local_g = uids("g:")
    groups: List[Dict[str, Any]] = []
    for uid in local_g + sorted({k.split(":")[1] for k in store_s if k.startswith("g:")} - set(local_g)):
        if merged.get(f"g:{uid}:gone") is True:
            groups.append({"uid": uid, "name": None, "members": None, "band": None, "gone": True})
            continue
        members = items.get(f"gm.{uid}")
        band = items.get(f"gb.{uid}")
        live = set(members or [])
        g_entry: Dict[str, Any] = {
            "uid": uid,
            "name": merged.get(f"g:{uid}:name"),
            "gone": False,
            "members": None if members is None else [item_pair(i) for i in members],
            "band": None if band is None else [item_pair(i) for i in band if i in live],
        }
        for field in _GROUP_OPT_FIELDS:
            if f"g:{uid}:{field}" in merged:
                g_entry[field] = merged[f"g:{uid}:{field}"]
        groups.append(g_entry)

    local_ly = uids("ly:")
    only_ly = sorted({k.split(":")[1] for k in store_s if k.startswith("ly:")} - set(local_ly),
                     key=lambda u: (min(s for k, (_v, s) in store_s.items() if k.startswith(f"ly:{u}:")), u))
    live_layouts: List[Dict[str, Any]] = []
    gone_layouts: List[Dict[str, Any]] = []
    for uid in local_ly + only_ly:
        if merged.get(f"ly:{uid}:gone") is True:
            if len(gone_layouts) < panel_layouts.MAX_TOMBS:
                gone_layouts.append({"uid": uid, "name": None, "shape": None, "style": None, "members": None, "gone": True})
            continue
        if len(live_layouts) >= panel_layouts.MAX_LAYOUTS:
            continue
        lid = f"lm.{uid}"
        ly_members = items.get(lid)
        s_bc = store_bc.get(lid, {})
        l_bc = (local_bc or {}).get(lid, {})
        member_rows: Optional[List[List[Any]]] = None
        if ly_members is not None:
            member_rows = []
            for item in ly_members:
                pair = item_pair(item)
                bc = s_bc[item] if item in s_bc else l_bc.get(item, True)
                member_rows.append([pair[0], pair[1], bool(bc)])
        ly_entry: Dict[str, Any] = {
            "uid": uid,
            "name": merged.get(f"ly:{uid}:name"),
            "gone": False,
            "members": member_rows,
        }
        for field in ("shape", "style"):
            if f"ly:{uid}:{field}" in merged:
                ly_entry[field] = merged[f"ly:{uid}:{field}"]
        live_layouts.append(ly_entry)
    layouts = live_layouts + gone_layouts

    bands: Dict[str, Any] = {}
    for lid in ids:
        if lid.startswith("b.p."):
            bands[f"p:{lid[4:]}"] = [item_pair(i) for i in items[lid]]
        elif lid.startswith("b."):
            bands[lid[2:]] = [item_pair(i) for i in items[lid]]
    return {
        "v": panel.VERSION,
        "companies": companies,
        "projects": projects,
        "groups": groups,
        "layouts": layouts,
        "arrangement": {
            "pinned": [item_pair(i) for i in items.get("pin", [])],
            "order": [item_pair(i) for i in items.get("ord", [])],
            "bands": bands,
            "sections": merged.get("a:sections"),
            "group_order": items.get("go") if "go" in items else None,
            "layout_order": items.get("lo") if "lo" in items else None,
        },
    }
