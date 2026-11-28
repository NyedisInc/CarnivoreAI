
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

import structlog

from src.core import resource_push, session_change_notice
from src.core.db import table_exists
from src.core.json_artifact import atomic_write_json
from src.core.pack.globalsync import mesh_workspace_dash as dash
from src.core.pack.machines import config_state
from src.core.pack.meshdata import hlc, workspace_kind
from src.core.resource_push import topics
from src.core.row_looks import registry as row_looks_registry
from src.core.ui_preferences.constants import ARRANGEMENT_SCHEMA_VERSION
from src.models.websocket import WSMessageType

log = structlog.get_logger(__name__)

SEEN_FILE = "mesh-workspace-seen.json"
KIND = workspace_kind.KIND
WORKSPACE_LOCK = threading.Lock()

_LOCAL_CO_FOLD_RE = re.compile(r"^c:([0-9]{1,18})$")
_LOCAL_PROJ_FOLD_RE = re.compile(r"^p:([0-9]{1,18})(:agents)?$")
_PORTABLE_CO_FOLD_RE = re.compile(r"^cu:([0-9a-f]{32})$")
_PORTABLE_PROJ_FOLD_RE = re.compile(r"^pu:([0-9a-f]{32})(:agents)?$")
_TOMB: Dict[str, bool] = {"gone": True}
_MAX_UI_RETRIES = 3

Rows = Mapping[str, Tuple[Any, hlc.Stamp]]


def value_hash(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


_TOMB_HASH = value_hash(_TOMB)


def synced_pref_snapshot(values: Mapping[str, Any]) -> Dict[str, Any]:
    snap = {name: values[name] for name in workspace_kind.SYNCED_TOP_PREFS if name in values}
    for extra in ("home_layout", "widget_state"):
        if extra in values:
            snap[extra] = values[extra]
    return snap


class Seen:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.store_id: Optional[str] = None
        self.scalars: Dict[str, str] = {}
        self.known_boards: Set[str] = set()
        self.known_charts: Set[str] = set()
        self.known_tripwires: Set[str] = set()
        self.known_annotations: Set[str] = set()
        self.known_widgets: Set[str] = set()
        self._loaded = ""

    def _payload(self) -> str:
        return json.dumps(
            {
                "v": 2,
                "store_id": self.store_id,
                "scalars": self.scalars,
                "known_boards": sorted(self.known_boards),
                "known_charts": sorted(self.known_charts),
                "known_tripwires": sorted(self.known_tripwires),
                "known_annotations": sorted(self.known_annotations),
                "known_widgets": sorted(self.known_widgets),
            },
            sort_keys=True,
        )

    @classmethod
    def load(cls, path: Path) -> "Seen":
        seen = cls(path)
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            scalars = raw["scalars"]
            if isinstance(scalars, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in scalars.items()):
                seen.store_id = raw["store_id"] if isinstance(raw.get("store_id"), str) else None
                seen.scalars = dict(scalars)
                for attr in ("known_boards", "known_charts", "known_tripwires", "known_annotations", "known_widgets"):
                    items = raw.get(attr)
                    if isinstance(items, list):
                        setattr(seen, attr, {x for x in items if isinstance(x, str)})
        except (OSError, ValueError, KeyError, TypeError):
            pass
        seen._loaded = seen._payload()
        return seen

    def save(self) -> None:
        text = self._payload()
        if text != self._loaded and atomic_write_json(self.path, json.loads(text), log_event="mesh_workspace_seen_write_failed"):
            self._loaded = text


class Ctx:

    def __init__(self, store: Any, signing: Any, lst: Any, own: str, gen: Optional[int] = None) -> None:
        self.store = store
        self.signing = signing
        self.lst = lst
        self.own = own
        self.gen = gen
        self.privileged = own in (lst.alpha, lst.home)

    def moved(self) -> bool:
        return self.gen is not None and self.store.generation != self.gen


class EntityMaps:

    def __init__(self, cid_to_uid: Dict[str, str], uid_to_cid: Dict[str, str], pid_to_uid: Dict[str, str], uid_to_pid: Dict[str, str]) -> None:
        self.cid_to_uid = cid_to_uid
        self.uid_to_cid = uid_to_cid
        self.pid_to_uid = pid_to_uid
        self.uid_to_pid = uid_to_pid

    def fingerprint(self) -> str:
        payload = json.dumps({"c": sorted(self.uid_to_cid), "p": sorted(self.uid_to_pid)}, separators=(",", ":"))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def load_entity_maps(conn: sqlite3.Connection) -> EntityMaps:
    cid_to_uid: Dict[str, str] = {}
    uid_to_cid: Dict[str, str] = {}
    pid_to_uid: Dict[str, str] = {}
    uid_to_pid: Dict[str, str] = {}
    if table_exists(conn, "companies"):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
        if "uid" in cols:
            for cid, cuid in conn.execute("SELECT id, uid FROM companies WHERE uid IS NOT NULL"):
                if isinstance(cuid, str) and len(cuid) == 32:
                    scid = str(cid)
                    cid_to_uid[scid] = cuid
                    uid_to_cid[cuid] = scid
    if table_exists(conn, "projects"):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
        if "uid" in cols:
            for pid, puid in conn.execute("SELECT id, uid FROM projects WHERE uid IS NOT NULL"):
                if isinstance(puid, str) and len(puid) == 32:
                    spid = str(pid)
                    pid_to_uid[spid] = puid
                    uid_to_pid[puid] = spid
    return EntityMaps(cid_to_uid, uid_to_cid, pid_to_uid, uid_to_pid)


def local_to_portable_collapsed(collapsed: Any, maps: EntityMaps) -> List[str]:
    if not isinstance(collapsed, list):
        return []
    out: List[str] = []
    for raw in collapsed:
        if not isinstance(raw, str):
            continue
        m_co = _LOCAL_CO_FOLD_RE.fullmatch(raw)
        if m_co is not None:
            cuid = maps.cid_to_uid.get(m_co.group(1))
            if cuid is not None:
                out.append(f"cu:{cuid}")
            continue
        m_proj = _LOCAL_PROJ_FOLD_RE.fullmatch(raw)
        if m_proj is not None:
            puid = maps.pid_to_uid.get(m_proj.group(1))
            if puid is not None:
                out.append(f"pu:{puid}{m_proj.group(2) or ''}")
            continue
        if workspace_kind.valid_portable_fold_key(raw):
            out.append(raw)
    return list(dict.fromkeys(out))


def portable_to_local_collapsed(portable: Any, maps: EntityMaps) -> List[str]:
    if not isinstance(portable, list):
        return []
    out: List[str] = []
    for raw in portable:
        if not isinstance(raw, str):
            continue
        m_co = _PORTABLE_CO_FOLD_RE.fullmatch(raw)
        if m_co is not None:
            cid = maps.uid_to_cid.get(m_co.group(1))
            if cid is not None:
                out.append(f"c:{cid}")
            continue
        m_proj = _PORTABLE_PROJ_FOLD_RE.fullmatch(raw)
        if m_proj is not None:
            pid = maps.uid_to_pid.get(m_proj.group(1))
            if pid is not None:
                out.append(f"p:{pid}{m_proj.group(2) or ''}")
            continue
        if workspace_kind.valid_portable_fold_key(raw):
            out.append(raw)
    return list(dict.fromkeys(out))


def _unmapped_remote_folds(remote_collapsed: Any, maps: EntityMaps) -> List[str]:
    if not isinstance(remote_collapsed, list):
        return []
    kept: List[str] = []
    for raw in remote_collapsed:
        if not isinstance(raw, str):
            continue
        m_co = _PORTABLE_CO_FOLD_RE.fullmatch(raw)
        if m_co is not None and m_co.group(1) not in maps.uid_to_cid:
            kept.append(raw)
            continue
        m_proj = _PORTABLE_PROJ_FOLD_RE.fullmatch(raw)
        if m_proj is not None and m_proj.group(1) not in maps.uid_to_pid:
            kept.append(raw)
    return kept


def _local_state(values: Mapping[str, Any], maps: EntityMaps, looks: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Optional[str]]]]:
    prefs: Dict[str, Any] = {f"pref:{name}": values.get(name) for name in workspace_kind.SYNCED_TOP_PREFS}
    arr = values.get("drawer_arrangement")
    arr_dict = arr if isinstance(arr, Mapping) else {}
    raw_po = arr_dict.get("projects_open")
    prefs["pref:projects_open"] = raw_po if isinstance(raw_po, bool) else None
    prefs["pref:desktop_collapsed"] = local_to_portable_collapsed(arr_dict.get("collapsed"), maps)
    rl_map: Dict[str, Dict[str, Optional[str]]] = {}
    for row_id, look in looks.items():
        if isinstance(row_id, str):
            entry = {"color": getattr(look, "color", None), "icon": getattr(look, "icon", None)}
            key = f"rl:{row_id}"
            if workspace_kind.valid(key, entry):
                rl_map[key] = entry
    return prefs, rl_map


def seed(
    ctx: Ctx,
    seen: Seen,
    prefs: Mapping[str, Any],
    rl_map: Mapping[str, Dict[str, Optional[str]]],
    extra_records: Mapping[str, Any] = (),  # type: ignore[assignment]
    known_sets: Optional[Tuple[Set[str], Set[str], Set[str], Set[str], Set[str]]] = None,
) -> int:
    extra = dict(extra_records) if extra_records else {}
    alpha = ctx.own == ctx.lst.alpha
    items: List[Tuple[str, Any, Optional[hlc.Stamp]]] = []
    if alpha:
        stamp = hlc.Stamp(1, 0, ctx.own)
        for key, value in prefs.items():
            if value is None or (key == "pref:desktop_collapsed" and value == []):
                continue
            if workspace_kind.valid(key, value):
                items.append((key, value, stamp))
        for key, entry in rl_map.items():
            items.append((key, entry, stamp))
        for key, entry in extra.items():
            if workspace_kind.valid(key, entry):
                items.append((key, entry, stamp))
    written = ctx.store.put_many(KIND, items, ctx.signing, ctx.lst, gen=ctx.gen)[0] if items else 0
    seen.scalars = {key: value_hash(value) for key, value in prefs.items() if workspace_kind.valid(key, value)}
    for key, entry in rl_map.items():
        seen.scalars[key] = value_hash(entry)
    for key, entry in extra.items():
        if workspace_kind.valid(key, entry):
            seen.scalars[key] = value_hash(entry)
    if known_sets is not None:
        seen.known_boards, seen.known_charts, seen.known_tripwires, seen.known_annotations, seen.known_widgets = (
            set(s) for s in known_sets
        )
    seen.store_id = ctx.store.store_id()
    return written


def _tombstone_keys_for_missing(
    seen: Seen,
    extra: Mapping[str, Any],
    cur_boards: Set[str],
    cur_charts: Set[str],
    cur_tripwires: Set[str],
    cur_annotations: Set[str],
    cur_widgets: Set[str],
) -> Set[str]:
    tomb_keys: Set[str] = set()
    for bid in seen.known_boards - cur_boards:
        tomb_keys.add(f"db:{bid}:head")
        tomb_keys.add(f"db:{bid}:rows")
        prefix = f"db:{bid}:"
        for k in seen.scalars:
            if k.startswith(prefix) and k not in extra:
                tomb_keys.add(k)
    for k in seen.scalars:
        if k.startswith("db:") and (":g." in k or ":r." in k) and k not in extra:
            tomb_keys.add(k)
    for cid in seen.known_charts - cur_charts:
        tomb_keys.add(f"sc:{cid}")
    for tid in seen.known_tripwires - cur_tripwires:
        tomb_keys.add(f"st:{tid}")
    for aid in seen.known_annotations - cur_annotations:
        tomb_keys.add(f"sa:{aid}")
    for wkey in seen.known_widgets - cur_widgets:
        tomb_keys.add(wkey)
    return tomb_keys


def observe(
    ctx: Ctx,
    seen: Seen,
    prefs: Mapping[str, Any],
    rl_map: Mapping[str, Dict[str, Optional[str]]],
    maps: EntityMaps,
    rows: Rows,
    extra_records: Optional[Mapping[str, Any]] = None,
    known_sets: Optional[Tuple[Set[str], Set[str], Set[str], Set[str], Set[str]]] = None,
) -> Set[str]:
    extra = dict(extra_records) if extra_records else {}
    cur_boards, cur_charts, cur_tripwires, cur_annotations, cur_widgets = (
        known_sets if known_sets is not None else (set(), set(), set(), set(), set())
    )
    items: List[Tuple[str, Any, Optional[hlc.Stamp]]] = []
    pending_hash: Dict[str, str] = {}
    pending_expected: Dict[str, Any] = {}

    for key, local_val in prefs.items():
        if not workspace_kind.valid(key, local_val):
            continue
        local_h = value_hash(local_val)
        if seen.scalars.get(key) == local_h:
            continue
        publish_val = local_val
        if key == "pref:desktop_collapsed" and key in rows:
            extra_folds = _unmapped_remote_folds(rows[key][0], maps)
            if extra_folds:
                merged = list(dict.fromkeys([*local_val, *extra_folds]))
                if workspace_kind.valid(key, merged):
                    publish_val = merged
        if key in rows and rows[key][0] == publish_val:
            seen.scalars[key] = local_h
            continue
        items.append((key, publish_val, None))
        pending_hash[key] = local_h
        pending_expected[key] = publish_val

    for key, entry in (*rl_map.items(), *extra.items()):
        if not workspace_kind.valid(key, entry):
            continue
        h = value_hash(entry)
        if seen.scalars.get(key) == h:
            continue
        if key in rows and rows[key][0] == entry:
            seen.scalars[key] = h
            continue
        items.append((key, entry, None))
        pending_hash[key] = h
        pending_expected[key] = entry

    tomb_keys = {k for k in list(seen.scalars) if k.startswith("rl:") and k not in rl_map}
    if known_sets is not None:
        tomb_keys |= _tombstone_keys_for_missing(
            seen, extra, cur_boards, cur_charts, cur_tripwires, cur_annotations, cur_widgets
        )
    for key in sorted(tomb_keys):
        if key == "ss:settings" or not workspace_kind.valid(key, _TOMB):
            continue
        if seen.scalars.get(key) == _TOMB_HASH:
            continue
        if key in rows and rows[key][0] == _TOMB:
            seen.scalars[key] = _TOMB_HASH
            continue
        items.append((key, _TOMB, None))
        pending_hash[key] = _TOMB_HASH
        pending_expected[key] = _TOMB

    if items:
        ctx.store.put_many(KIND, items, ctx.signing, ctx.lst, gen=ctx.gen)
    fresh = ctx.store.kind_rows(ctx.lst, KIND) if items else rows
    refused: Set[str] = set()
    for key, h in pending_hash.items():
        if key in fresh and fresh[key][0] == pending_expected[key]:
            seen.scalars[key] = h
        else:
            refused.add(key)

    if known_sets is not None:
        seen.known_boards = {b for b in cur_boards if f"db:{b}:head" not in refused} | {
            b for b in seen.known_boards - cur_boards if f"db:{b}:head" in refused
        }
        seen.known_charts = {c for c in cur_charts if f"sc:{c}" not in refused} | {
            c for c in seen.known_charts - cur_charts if f"sc:{c}" in refused
        }
        seen.known_tripwires = {t for t in cur_tripwires if f"st:{t}" not in refused} | {
            t for t in seen.known_tripwires - cur_tripwires if f"st:{t}" in refused
        }
        seen.known_annotations = {a for a in cur_annotations if f"sa:{a}" not in refused} | {
            a for a in seen.known_annotations - cur_annotations if f"sa:{a}" in refused
        }
        seen.known_widgets = {w for w in cur_widgets if w not in refused} | {
            w for w in seen.known_widgets - cur_widgets if w in refused
        }
    return refused


def _build_ui_patch(values: Mapping[str, Any], rows: Rows, maps: EntityMaps, held: Set[str]) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    for name in workspace_kind.SYNCED_TOP_PREFS:
        key = f"pref:{name}"
        if key not in rows or key in held:
            continue
        remote_val = rows[key][0]
        if values.get(name) != remote_val:
            patch[name] = remote_val

    cur_arr = values.get("drawer_arrangement")
    arr_dict = dict(cur_arr) if isinstance(cur_arr, Mapping) else None
    arr_changed = False
    new_arr: Dict[str, Any] = (
        dict(arr_dict)
        if arr_dict is not None
        else {"v": ARRANGEMENT_SCHEMA_VERSION, "pinned": [], "order": [], "bands": {}, "collapsed": []}
    )

    po_key = "pref:projects_open"
    if po_key in rows and po_key not in held:
        remote_po = rows[po_key][0]
        cur_po = arr_dict.get("projects_open") if arr_dict is not None else None
        if cur_po != remote_po:
            new_arr["projects_open"] = remote_po
            arr_changed = True

    dc_key = "pref:desktop_collapsed"
    if dc_key in rows and dc_key not in held:
        remote_dc = rows[dc_key][0]
        target_local = portable_to_local_collapsed(remote_dc, maps) if isinstance(remote_dc, list) else []
        cur_collapsed = list(arr_dict.get("collapsed") or []) if arr_dict is not None else []
        if cur_collapsed != target_local:
            new_arr["collapsed"] = target_local
            arr_changed = True

    if arr_changed:
        patch["drawer_arrangement"] = new_arr

    next_hl = dash.reconstruct_home_layout(values.get("home_layout"), rows, held)
    if next_hl is not dash.NO_CHANGE:
        patch["home_layout"] = next_hl

    next_ws = dash.reconstruct_widget_state(values.get("widget_state"), rows, held)
    if next_ws is not dash.NO_CHANGE:
        patch["widget_state"] = next_ws

    return patch


def _apply_ui_preferences(ui_store: Any, rows: Rows, maps: EntityMaps, held: Set[str]) -> Tuple[Any, Mapping[str, Any]]:
    last_result: Any = None
    for _ in range(_MAX_UI_RETRIES):
        block = ui_store.read() or {}
        values = block.get("values") if isinstance(block.get("values"), Mapping) else {}
        patch = _build_ui_patch(values, rows, maps, held)
        if not patch:
            return last_result, values
        rev = block.get("revision") if isinstance(block.get("revision"), int) else None
        result = ui_store.update(patch, expected_revision=rev) if rev is not None else ui_store.update(patch)
        last_result = result
        if getattr(result, "status", None) == "stale_revision":
            continue
        latest_values = result.values if isinstance(getattr(result, "values", None), Mapping) else values
        return result, latest_values
    final_block = ui_store.read() or {}
    final_values = final_block.get("values") if isinstance(final_block.get("values"), Mapping) else {}
    return last_result, final_values


def _apply_row_looks(row_looks_api: Any, rows: Rows, held: Set[str], seen: Seen) -> bool:
    local = row_looks_api.listing()
    changed = False
    for key, (val, _stamp) in rows.items():
        if not key.startswith("rl:") or key in held:
            continue
        row_id = key[3:]
        if workspace_kind.is_tomb(val):
            if row_id in local:
                row_looks_api.forget(row_id)
                changed = True
            seen.scalars[key] = _TOMB_HASH
            continue
        if not isinstance(val, dict):
            continue
        color = val.get("color")
        icon = val.get("icon")
        cur = local.get(row_id)
        if cur is None or cur.color != color or cur.icon != icon:
            row_looks_api.set_look(row_id, {"color": color, "icon": icon})
            changed = True
        seen.scalars[key] = value_hash({"color": color, "icon": icon})
    return changed


def _rebase_seen_prefs(seen: Seen, values: Mapping[str, Any], maps: EntityMaps, held: Set[str], rows: Optional[Rows] = None) -> None:
    prefs, _rl = _local_state(values, maps, {})
    for key, val in prefs.items():
        if key not in held and workspace_kind.valid(key, val):
            seen.scalars[key] = value_hash(val)
    db_recs, board_ids = dash.collect_dashboards(values)
    for key, val in db_recs.items():
        if key not in held and workspace_kind.valid(key, val):
            seen.scalars[key] = value_hash(val)
    seen.known_boards = {b for b in board_ids if f"db:{b}:head" not in held} | {
        b for b in seen.known_boards if f"db:{b}:head" in held
    }
    wst_recs, wst_keys = dash.collect_widget_state(values)
    for key, val in wst_recs.items():
        if key not in held and workspace_kind.valid(key, val):
            seen.scalars[key] = value_hash(val)
    seen.known_widgets = {w for w in seen.known_widgets if not w.startswith("wst:") or w in held} | {
        w for w in wst_keys if w not in held
    }
    if rows is not None:
        for key, (val, _stamp) in rows.items():
            if key not in held and workspace_kind.is_tomb(val) and (key.startswith("db:") or key.startswith("wst:")):
                seen.scalars[key] = _TOMB_HASH


def _may_apply(ctx: Ctx) -> bool:
    return ctx.privileged or bool(config_state.default().restrictions().may_receive_pack_ui)


async def announce(
    app_state: Any,
    ui_result: Any,
    looks_changed: bool,
    stats_changed: bool = False,
    stats_rev: Optional[int] = None,
    stats_settings: Optional[Dict[str, Any]] = None,
    item_settings_changed: bool = False,
    item_settings_rev: int = 0,
) -> None:
    if ui_result is not None and getattr(ui_result, "status", None) == "committed":
        from src.core.preferences_push.broadcast import broadcast_changed

        await broadcast_changed(app_state, ui_result, None)
    if looks_changed:
        resource_push.notify(topics.ROW_LOOKS)
    if stats_changed:
        if stats_settings is not None:
            scheduler = getattr(app_state, "stats_scheduler", None)
            if scheduler is not None and hasattr(scheduler, "settings_changed"):
                res = scheduler.settings_changed(stats_settings)
                if asyncio.iscoroutine(res):
                    await res
        if stats_rev is not None:
            session_change_notice.publish(
                app_state,
                {"type": "stats.changed", "revision": stats_rev, "source_health": "ok"},
            )
    if item_settings_changed:
        session_change_notice.publish(
            app_state,
            {"type": WSMessageType.ITEM_SETTINGS_CHANGED, "revision": item_settings_rev},
        )
        resource_push.notify(topics.ITEM_SETTINGS)


def attach(
    app_state: Any,
    open_db: Callable[[], Any],
    settings: Callable[[], Mapping[str, Any]],
    state_dir: Path,
    *,
    row_looks_api: Any = None,
    stats_store: Any = None,
) -> Callable[[Any, Any], Any]:
    seen_path = Path(state_dir) / SEEN_FILE
    looks_api = row_looks_registry if row_looks_api is None else row_looks_api
    state: Dict[str, Optional[str]] = {"digest": None}

    def work(service: Any, lst: Any) -> Optional[Tuple[Any, bool, bool, Optional[int], Optional[Dict[str, Any]], bool, int]]:
        ui_store = app_state.ui_preferences_store
        ctx = Ctx(service.store, service.signing, lst, service.store.own_iid, service.pass_gen)
        with WORKSPACE_LOCK:
            seen = Seen.load(seen_path)
            if ctx.moved():
                return None

            with closing(open_db()) as conn:
                maps = load_entity_maps(conn)
                ws_recs, ws_keys = dash.collect_item_settings(conn)

            block = ui_store.read() or {}
            values = block.get("values") if isinstance(block.get("values"), Mapping) else {}
            prefs, rl_map = _local_state(values, maps, looks_api.listing())
            db_recs, board_ids = dash.collect_dashboards(values)
            wst_recs, wst_keys = dash.collect_widget_state(values)
            resolved_stats = dash.resolve_stats_store(app_state, state_dir, explicit=stats_store)
            stats_recs, chart_ids, tripwire_ids, ann_ids = dash.collect_stats(resolved_stats, ctx.own)

            extra_records: Dict[str, Any] = {**db_recs, **stats_recs, **ws_recs, **wst_recs}
            known_sets = (board_ids, chart_ids, tripwire_ids, ann_ids, ws_keys | wst_keys)

            sid = ctx.store.store_id()
            if seen.store_id != sid:
                seed(ctx, seen, prefs, rl_map, extra_records, known_sets)
                if not ctx.moved():
                    seen.save()
                return None

            rows = ctx.store.kind_rows(lst, KIND)
            held = observe(ctx, seen, prefs, rl_map, maps, rows, extra_records, known_sets)
            digest = f"{ctx.store.kind_digest(lst, KIND)}:{maps.fingerprint()}"

            if not (_may_apply(ctx) and digest != state["digest"]):
                if not ctx.moved():
                    seen.save()
                return None

            fresh = ctx.store.kind_rows(lst, KIND)
            ui_result, committed_values = _apply_ui_preferences(ui_store, fresh, maps, held)
            looks_changed = _apply_row_looks(looks_api, fresh, held, seen)
            stats_changed, stats_rev, stats_settings = dash.apply_stats(resolved_stats, fresh, held, ctx.own, seen)
            with closing(open_db()) as conn:
                item_settings_changed, item_settings_rev = dash.apply_item_settings(conn, fresh, held, seen)

            if ui_result is None or getattr(ui_result, "status", None) in ("committed", "unchanged"):
                _rebase_seen_prefs(seen, committed_values, maps, held, fresh)
            else:
                log.warning("mesh_workspace_apply_rejected", status=getattr(ui_result, "status", None))
            if not ctx.moved():
                seen.save()
            state["digest"] = f"{ctx.store.kind_digest(lst, KIND)}:{maps.fingerprint()}"
            return ui_result, looks_changed, stats_changed, stats_rev, stats_settings, item_settings_changed, item_settings_rev

    async def step(service: Any, lst: Any) -> None:
        if app_state.ui_preferences_store is None or not settings().get("panel") or not workspace_kind.approved(lst, service.store.own_iid):
            return
        done = await asyncio.to_thread(work, service, lst)
        if done is not None:
            await announce(app_state, *done)

    return step
