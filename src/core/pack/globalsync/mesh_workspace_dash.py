
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import structlog
from pydantic import ValidationError

from src.core import item_catalog, item_settings_store
from src.core.db import table_exists, transaction
from src.core.item_settings_ddl import ITEM_SETTINGS_TABLE
from src.core.item_settings_schema import check_key
from src.core.pack.globalsync.mesh_workspace_stats import (
    TOMB,
    TOMB_HASH,
    apply_stats,
    collect_stats,
    normalize_host_for_local,
    normalize_host_for_wire,
    resolve_stats_store,
    value_hash,
)
from src.core.pack.meshdata import hlc, workspace_kind
from src.core.trail_entry import utc_now
from src.core.ui_preferences.constants import MAX_ANALYTICS_SEED, MAX_WIDGET_STATE_ENTRIES
from src.core.ui_preferences.layouts import HomeLayout
from src.core.ui_preferences.sidebar_checks import check_widget_state

log = structlog.get_logger(__name__)

Rows = Mapping[str, Tuple[Any, hlc.Stamp]]

ROWS_INLINE_LIMIT = 3500
ROWS_CHUNK_CHARS = 3400


class _NoChangeType:
    pass


NO_CHANGE = _NoChangeType()

__all__ = [
    "NO_CHANGE",
    "ROWS_CHUNK_CHARS",
    "ROWS_INLINE_LIMIT",
    "TOMB",
    "TOMB_HASH",
    "apply_item_settings",
    "apply_stats",
    "collect_dashboards",
    "collect_item_settings",
    "collect_stats",
    "collect_widget_state",
    "normalize_host_for_local",
    "normalize_host_for_wire",
    "reconstruct_home_layout",
    "reconstruct_widget_state",
    "resolve_stats_store",
    "value_hash",
]




def _cell_record_key(board_id: str, cell_id: str) -> Tuple[str, bool]:
    direct = f"db:{board_id}:g.{cell_id}"
    if workspace_kind.valid(direct, {"id": cell_id}):
        return direct, False
    hashed = hashlib.sha1(cell_id.encode("utf-8")).hexdigest()[:16]
    return f"db:{board_id}:g.h_{hashed}", True


def _split_grid(board_id: str, grid: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    cell_records: Dict[str, Dict[str, Any]] = {}
    layouts = grid.get("layouts")
    if isinstance(layouts, dict):
        meta = {k: v for k, v in grid.items() if k != "layouts" and isinstance(k, str) and not workspace_kind.is_secret_field(k)}
        meta["_mode"] = "layouts"
        col_keys = [ck for ck in layouts if isinstance(ck, str) and isinstance(layouts[ck], list)]
        meta["_cols"] = sorted(col_keys)
        ordered_ids: List[str] = []
        seen_ids: Set[str] = set()
        for ck in (["24", *[k for k in sorted(col_keys) if k != "24"]] if "24" in col_keys else sorted(col_keys)):
            for item in layouts[ck]:
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    ordered_ids.append(item["id"])
        by_col: Dict[str, Dict[str, Tuple[int, Dict[str, Any]]]] = {}
        for ck in col_keys:
            col_map: Dict[str, Tuple[int, Dict[str, Any]]] = {}
            for pos, item in enumerate(layouts[ck]):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    col_map[item["id"]] = (pos, {k: v for k, v in item.items() if k != "id"})
            by_col[ck] = col_map
        for ord_idx, cid in enumerate(ordered_ids):
            rec: Dict[str, Any] = {"id": cid, "ord": ord_idx}
            for ck in col_keys:
                entry = by_col[ck].get(cid)
                if entry is not None:
                    pos, props = entry
                    rec[f"l{ck}"] = workspace_kind.strip_secret_keys(props)
                    if ck != "24":
                        rec[f"o{ck}"] = pos
            key, _hashed = _cell_record_key(board_id, cid)
            if workspace_kind.valid(key, rec):
                cell_records[key] = rec
        return meta, cell_records

    cells = grid.get("cells")
    if isinstance(cells, dict):
        meta = {k: v for k, v in grid.items() if k != "cells" and isinstance(k, str) and not workspace_kind.is_secret_field(k)}
        meta["_mode"] = "cells"
        for cid, cval in cells.items():
            if not isinstance(cid, str) or not isinstance(cval, dict):
                continue
            key, hashed = _cell_record_key(board_id, cid)
            rec = workspace_kind.strip_secret_keys(cval)
            if hashed:
                rec["_cid"] = cid
            if workspace_kind.valid(key, rec):
                cell_records[key] = rec
        return meta, cell_records

    return {}, {}


def collect_dashboards(values: Mapping[str, Any]) -> Tuple[Dict[str, Any], Set[str]]:
    hl = values.get("home_layout")
    if not isinstance(hl, Mapping):
        return {}, set()
    boards = hl.get("boards")
    if not isinstance(boards, list) or not boards:
        return {}, set()

    records: Dict[str, Any] = {}
    board_ids: Set[str] = set()
    order: List[str] = []

    for board in boards:
        if not isinstance(board, Mapping):
            continue
        bid = board.get("id")
        name = board.get("name")
        layout = board.get("layout")
        if not isinstance(bid, str) or not isinstance(name, str) or not isinstance(layout, Mapping):
            continue
        rows_list = layout.get("rows")
        if not isinstance(rows_list, list) or not rows_list:
            continue

        order.append(bid)
        board_ids.add(bid)

        head: Dict[str, Any] = {
            "name": name,
            "v": layout.get("v", 6),
            "hidden": layout.get("hidden", []),
            "heroCollapsed": layout.get("heroCollapsed", False),
            "collapsed": layout.get("collapsed", []),
        }
        if "headerOff" in layout:
            head["headerOff"] = layout["headerOff"]
        if isinstance(board.get("icon"), str):
            head["icon"] = board["icon"]
        for extra_k, extra_v in layout.items():
            if extra_k not in ("v", "rows", "hidden", "heroCollapsed", "collapsed", "headerOff", "grid") and isinstance(extra_k, str) and not workspace_kind.is_secret_field(extra_k):
                head[extra_k] = workspace_kind.strip_secret_keys(extra_v)

        grid = layout.get("grid")
        if isinstance(grid, Mapping):
            grid_meta, cell_records = _split_grid(bid, grid)
            if grid_meta:
                head["grid_meta"] = grid_meta
                records.update(cell_records)
            else:
                head["grid_raw"] = workspace_kind.strip_secret_keys(dict(grid))

        head_key = f"db:{bid}:head"
        if workspace_kind.valid(head_key, head):
            records[head_key] = head

        rows_clean = workspace_kind.strip_secret_keys(rows_list)
        rows_text = json.dumps(rows_clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        rows_key = f"db:{bid}:rows"
        if len(rows_text) <= ROWS_INLINE_LIMIT and workspace_kind.valid(rows_key, rows_clean):
            records[rows_key] = rows_clean
        else:
            chunks = [rows_text[i:i + ROWS_CHUNK_CHARS] for i in range(0, len(rows_text), ROWS_CHUNK_CHARS)]
            header = {"chunked": True, "n": len(chunks)}
            if workspace_kind.valid(rows_key, header):
                records[rows_key] = header
                for idx, chunk in enumerate(chunks):
                    ckey = f"db:{bid}:r.{idx}"
                    cval = {"i": idx, "n": len(chunks), "data": chunk}
                    if workspace_kind.valid(ckey, cval):
                        records[ckey] = cval

    if not order:
        return {}, set()

    meta: Dict[str, Any] = {
        "active": hl.get("active") if isinstance(hl.get("active"), str) else None,
        "order": order,
        "analytics_seed": int(hl.get("analytics_seed", 0)),
    }
    if workspace_kind.valid("db:meta", meta):
        records["db:meta"] = meta
    return records, board_ids


def _reassemble_rows(bid: str, rows: Rows, held: Set[str]) -> Optional[List[Any]]:
    rkey = f"db:{bid}:rows"
    if rkey not in rows or rkey in held:
        return None
    rval = rows[rkey][0]
    if workspace_kind.is_tomb(rval):
        return None
    if isinstance(rval, list):
        return rval if rval else None
    if isinstance(rval, dict) and rval.get("chunked") is True:
        count = rval.get("n")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0 or count > 1000:
            return None
        parts: List[str] = []
        for idx in range(count):
            ckey = f"db:{bid}:r.{idx}"
            if ckey not in rows or ckey in held:
                return None
            cval = rows[ckey][0]
            if not isinstance(cval, dict) or workspace_kind.is_tomb(cval) or cval.get("i") != idx or cval.get("n") != count or not isinstance(cval.get("data"), str):
                return None
            parts.append(cval["data"])
        try:
            decoded = json.loads("".join(parts))
        except ValueError:
            return None
        return decoded if isinstance(decoded, list) and decoded else None
    return None


def _reassemble_grid(bid: str, grid_meta: Mapping[str, Any], rows: Rows, held: Set[str]) -> Dict[str, Any]:
    prefix = f"db:{bid}:g."
    gm = dict(grid_meta)
    mode = gm.pop("_mode", "layouts")
    col_keys = gm.pop("_cols", ["24"])
    cell_items: List[Tuple[str, Dict[str, Any]]] = []
    for key, (val, _stamp) in rows.items():
        if not key.startswith(prefix) or key in held or workspace_kind.is_tomb(val) or not isinstance(val, dict):
            continue
        cell_items.append((key[len(prefix):], val))

    if mode == "cells":
        cells_map: Dict[str, Any] = {}
        for suffix, val in cell_items:
            cid = val.get("_cid") if isinstance(val.get("_cid"), str) else suffix
            cells_map[cid] = {k: v for k, v in val.items() if k != "_cid"}
        return {**gm, "cells": cells_map}

    valid_cols = [ck for ck in col_keys if isinstance(ck, str)] or ["24"]
    buckets: Dict[str, List[Tuple[int, str, Dict[str, Any]]]] = {ck: [] for ck in valid_cols}
    for suffix, val in cell_items:
        cid = val.get("id") if isinstance(val.get("id"), str) else suffix
        ord24 = val.get("ord") if isinstance(val.get("ord"), int) else 0
        for ck in valid_cols:
            lk = f"l{ck}"
            if isinstance(val.get(lk), dict):
                pos = ord24 if ck == "24" else (val.get(f"o{ck}") if isinstance(val.get(f"o{ck}"), int) else ord24)
                buckets[ck].append((pos, cid, {"id": cid, **val[lk]}))
    layouts_out = {ck: [item for _, _, item in sorted(entries, key=lambda t: (t[0], t[1]))] for ck, entries in buckets.items()}
    return {**gm, "layouts": layouts_out}


def reconstruct_home_layout(current_hl: Any, rows: Rows, held: Set[str]) -> Any:
    has_db = any(k == "db:meta" or k.startswith("db:") for k in rows if k not in held)
    if not has_db:
        return NO_CHANGE

    local_boards: Dict[str, Dict[str, Any]] = {}
    if isinstance(current_hl, Mapping) and isinstance(current_hl.get("boards"), list):
        for b in current_hl["boards"]:
            if isinstance(b, Mapping) and isinstance(b.get("id"), str):
                local_boards[b["id"]] = dict(b)

    meta: Mapping[str, Any] = {}
    if "db:meta" in rows and "db:meta" not in held and isinstance(rows["db:meta"][0], Mapping):
        meta = rows["db:meta"][0]

    live_heads: Dict[str, Dict[str, Any]] = {}
    tomb_boards: Set[str] = set()
    for key, (val, _stamp) in rows.items():
        if key in held or not key.startswith("db:") or not key.endswith(":head"):
            continue
        bid = key[3:-5]
        if workspace_kind.is_tomb(val):
            tomb_boards.add(bid)
        elif isinstance(val, dict) and isinstance(val.get("name"), str):
            live_heads[bid] = val

    ordered_ids: List[str] = []
    raw_order = meta.get("order")
    if isinstance(raw_order, list):
        for bid in raw_order:
            if isinstance(bid, str) and bid not in tomb_boards and bid in live_heads and bid not in ordered_ids:
                ordered_ids.append(bid)
    for bid in sorted(live_heads):
        if bid not in ordered_ids and bid not in tomb_boards:
            ordered_ids.append(bid)

    rebuilt_boards: List[Dict[str, Any]] = []
    for bid in ordered_ids:
        head = live_heads[bid]
        board_rows = _reassemble_rows(bid, rows, held)
        if board_rows is None:
            if bid in local_boards:
                rebuilt_boards.append(local_boards[bid])
            continue
        layout: Dict[str, Any] = {
            "v": head.get("v", 6),
            "rows": board_rows,
            "hidden": head.get("hidden", []),
            "heroCollapsed": head.get("heroCollapsed", False),
            "collapsed": head.get("collapsed", []),
        }
        if "headerOff" in head:
            layout["headerOff"] = head["headerOff"]
        for extra_k, extra_v in head.items():
            if extra_k not in ("name", "icon", "v", "hidden", "heroCollapsed", "collapsed", "headerOff", "grid_meta", "grid_raw"):
                layout[extra_k] = extra_v
        if isinstance(head.get("grid_meta"), Mapping):
            layout["grid"] = _reassemble_grid(bid, head["grid_meta"], rows, held)
        elif isinstance(head.get("grid_raw"), Mapping):
            layout["grid"] = dict(head["grid_raw"])
        rebuilt_boards.append({"id": bid, "name": head["name"], "layout": layout})

    if not rebuilt_boards:
        return NO_CHANGE

    seed_raw = meta.get("analytics_seed", current_hl.get("analytics_seed", 0) if isinstance(current_hl, Mapping) else 0)
    seed_val = max(0, min(MAX_ANALYTICS_SEED, int(seed_raw))) if isinstance(seed_raw, int) and not isinstance(seed_raw, bool) else 0
    candidate: Dict[str, Any] = {"v": 2, "boards": rebuilt_boards, "analytics_seed": seed_val}
    active = meta.get("active")
    if isinstance(active, str) and any(b["id"] == active for b in rebuilt_boards):
        candidate["active"] = active

    try:
        validated = HomeLayout.model_validate(candidate).model_dump(mode="json")
    except ValidationError as exc:
        log.warning("mesh_workspace_dash_home_layout_invalid", error=str(exc)[:160])
        return NO_CHANGE
    return NO_CHANGE if validated == current_hl else validated




def _ws_key(kind: str, item_id: str) -> str:
    return f"ws:{item_id}" if kind == item_catalog.KIND_WIDGET else f"ws:{kind}:{item_id}"


def _parse_ws_key(key: str) -> Tuple[str, str]:
    rest = key[3:]
    if ":" in rest:
        prefix, tail = rest.split(":", 1)
        if prefix in item_catalog.KINDS:
            return prefix, tail
    return item_catalog.KIND_WIDGET, rest


def collect_item_settings(conn: sqlite3.Connection) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
    if not table_exists(conn, ITEM_SETTINGS_TABLE):
        return {}, set()
    conn.row_factory = sqlite3.Row
    records: Dict[str, Dict[str, Any]] = {}
    keys: Set[str] = set()
    for row in conn.execute(f"SELECT kind, item_id, enabled, values_json FROM {ITEM_SETTINGS_TABLE} ORDER BY kind, item_id"):
        kind = str(row["kind"])
        item_id = str(row["item_id"])
        enabled = None if row["enabled"] is None else bool(row["enabled"])
        try:
            raw = json.loads(row["values_json"])
        except ValueError:
            raw = {}
        clean = workspace_kind.strip_secret_keys(raw) if isinstance(raw, dict) else {}
        if enabled is None and not clean:
            continue
        key = _ws_key(kind, item_id)
        payload: Dict[str, Any] = {"enabled": enabled, "settings": clean}
        if workspace_kind.valid(key, payload):
            records[key] = payload
            keys.add(key)
    return records, keys


def apply_item_settings(conn: sqlite3.Connection, rows: Rows, held: Set[str], seen: Any) -> Tuple[bool, int]:
    if not table_exists(conn, ITEM_SETTINGS_TABLE):
        return False, 0
    conn.row_factory = sqlite3.Row
    changed = False
    with transaction(conn):
        for key, (val, _stamp) in rows.items():
            if not key.startswith("ws:") or key in held:
                continue
            kind, item_id = _parse_ws_key(key)
            cur = conn.execute(
                f"SELECT enabled, values_json, schema_version, revision FROM {ITEM_SETTINGS_TABLE} WHERE kind=? AND item_id=?",
                (kind, item_id),
            ).fetchone()
            if workspace_kind.is_tomb(val):
                if cur is not None:
                    conn.execute(f"DELETE FROM {ITEM_SETTINGS_TABLE} WHERE kind=? AND item_id=?", (kind, item_id))
                    changed = True
                seen.scalars[key] = TOMB_HASH
                seen.known_widgets.discard(key)
                continue
            if not isinstance(val, dict):
                continue
            raw_enabled = val.get("enabled")
            if raw_enabled is not None and not isinstance(raw_enabled, bool):
                continue
            raw_settings = val.get("settings")
            clean_settings = workspace_kind.strip_secret_keys(raw_settings) if isinstance(raw_settings, dict) else {}
            decl = item_catalog.find(kind, item_id)
            if decl is not None:
                eff_enabled = raw_enabled if decl.switchable else None
                schema_ver = decl.schema.version if decl.schema is not None else None
                accepted: Dict[str, Any] = {}
                if decl.schema is not None:
                    for sk, sv in clean_settings.items():
                        if check_key(decl.schema, sk, sv) is None:
                            accepted[sk] = sv
            else:
                eff_enabled = raw_enabled
                schema_ver = None
                accepted = clean_settings

            cur_enabled = None if cur is None or cur["enabled"] is None else bool(cur["enabled"])
            try:
                cur_vals = workspace_kind.strip_secret_keys(json.loads(cur["values_json"])) if cur is not None else {}
            except ValueError:
                cur_vals = {}

            if cur is None or cur_enabled != eff_enabled or cur_vals != accepted:
                next_rev = item_settings_store.document_revision(conn) + 1
                conn.execute(
                    f"INSERT INTO {ITEM_SETTINGS_TABLE} "
                    "(kind, item_id, enabled, schema_version, values_json, revision, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(kind, item_id) DO UPDATE SET "
                    "enabled = excluded.enabled, schema_version = excluded.schema_version, "
                    "values_json = excluded.values_json, revision = excluded.revision, "
                    "updated_at = excluded.updated_at",
                    (
                        kind, item_id, None if eff_enabled is None else int(eff_enabled),
                        schema_ver, json.dumps(accepted, sort_keys=True), next_rev, utc_now(),
                    ),
                )
                changed = True
            seen.scalars[key] = value_hash({"enabled": eff_enabled, "settings": accepted})
            seen.known_widgets.add(key)
        doc_rev = item_settings_store.document_revision(conn)
    return changed, doc_rev




def collect_widget_state(values: Mapping[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
    ws = values.get("widget_state")
    if not isinstance(ws, Mapping):
        return {}, set()
    records: Dict[str, Dict[str, Any]] = {}
    keys: Set[str] = set()
    for wid, state in ws.items():
        if not isinstance(wid, str) or not isinstance(state, dict):
            continue
        clean = workspace_kind.strip_secret_keys(state)
        key = f"wst:{wid}"
        if workspace_kind.valid(key, clean):
            records[key] = clean
            keys.add(key)
    return records, keys


def reconstruct_widget_state(current_ws: Any, rows: Rows, held: Set[str]) -> Any:
    merged: Dict[str, Dict[str, Any]] = dict(current_ws) if isinstance(current_ws, Mapping) else {}
    touched = False
    for key, (val, _stamp) in rows.items():
        if not key.startswith("wst:") or key in held:
            continue
        wid = key[4:]
        if workspace_kind.is_tomb(val):
            if wid in merged:
                merged.pop(wid, None)
                touched = True
            continue
        if not isinstance(val, dict):
            continue
        clean = workspace_kind.strip_secret_keys(val)
        if merged.get(wid) != clean:
            if wid not in merged and len(merged) >= MAX_WIDGET_STATE_ENTRIES:
                continue
            merged[wid] = clean
            touched = True
    if not touched:
        return NO_CHANGE
    if not merged:
        return None if current_ws is not None else NO_CHANGE
    try:
        validated = check_widget_state(merged)
    except ValueError as exc:
        log.warning("mesh_workspace_dash_widget_state_invalid", error=str(exc)[:120])
        return NO_CHANGE
    return NO_CHANGE if validated == current_ws else validated
