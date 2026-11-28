
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import structlog
from pydantic import ValidationError

from src.core.db import table_exists
from src.core.pack.meshdata import hlc, workspace_kind
from src.core.stats import config as stats_config
from src.core.stats.store import StatsStore
from src.models.stats import AnnotationWrite, ChartWrite, TripwireWrite

log = structlog.get_logger(__name__)

Rows = Mapping[str, Tuple[Any, hlc.Stamp]]
TOMB: Dict[str, bool] = {"gone": True}


def value_hash(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


TOMB_HASH = value_hash(TOMB)


def resolve_stats_store(app_state: Any, state_dir: Path, explicit: Any = None) -> Optional[Any]:
    candidate = explicit if explicit is not None else getattr(app_state, "stats_store", None)
    if candidate is not None:
        return candidate if Path(candidate.db_path).exists() else None
    for root in (Path(state_dir).parent, Path(state_dir)):
        store = StatsStore(root)
        if Path(store.db_path).exists():
            return store
    return None


def normalize_host_for_wire(filters: Any, own_iid: str) -> Any:
    if not isinstance(filters, dict):
        return filters
    out = dict(filters)
    if out.get("host") == "local":
        out["host"] = own_iid
    if isinstance(out.get("hosts"), list):
        out["hosts"] = [own_iid if h == "local" else h for h in out["hosts"]]
    return out


def normalize_host_for_local(filters: Any, own_iid: str) -> Any:
    if not isinstance(filters, dict):
        return filters
    out = dict(filters)
    if out.get("host") == own_iid:
        out["host"] = "local"
    if isinstance(out.get("hosts"), list):
        out["hosts"] = ["local" if h == own_iid else h for h in out["hosts"]]
    return out


def _normalize_chart_hosts(cfg: Mapping[str, Any], own_iid: str, *, for_wire: bool) -> Dict[str, Any]:
    fn = normalize_host_for_wire if for_wire else normalize_host_for_local
    out = dict(cfg)
    if "filters" in out:
        out["filters"] = fn(out["filters"], own_iid)
    if isinstance(out.get("series"), list):
        new_series: List[Any] = []
        for item in out["series"]:
            if isinstance(item, dict) and "filters" in item:
                copy = dict(item)
                copy["filters"] = fn(item["filters"], own_iid)
                new_series.append(copy)
            else:
                new_series.append(item)
        out["series"] = new_series
    return out


def collect_stats(stats_store: Optional[Any], own_iid: str) -> Tuple[Dict[str, Any], Set[str], Set[str], Set[str]]:
    if stats_store is None or not Path(stats_store.db_path).exists():
        return {}, set(), set(), set()

    records: Dict[str, Any] = {}
    chart_ids: Set[str] = set()
    tripwire_ids: Set[str] = set()
    ann_ids: Set[str] = set()

    try:
        with stats_store.connect(readonly=True) as db:
            if table_exists(db, "stats_charts"):
                for row in db.execute("SELECT id, config_json FROM stats_charts ORDER BY id"):
                    cid = str(row["id"])
                    try:
                        raw_cfg = json.loads(row["config_json"])
                    except ValueError:
                        continue
                    if not isinstance(raw_cfg, dict):
                        continue
                    payload = _normalize_chart_hosts(raw_cfg, own_iid, for_wire=True)
                    key = f"sc:{cid}"
                    if workspace_kind.valid(key, payload):
                        records[key] = payload
                        chart_ids.add(cid)

            if table_exists(db, "stats_tripwires"):
                for row in db.execute(
                    "SELECT id, chart_id, name, query, window_minutes, comparator, threshold, "
                    "for_minutes, cooldown_minutes, enabled FROM stats_tripwires ORDER BY id"
                ):
                    tid = str(row["id"])
                    try:
                        raw_q = json.loads(row["query"])
                    except ValueError:
                        continue
                    if not isinstance(raw_q, dict):
                        continue
                    q_wire = dict(raw_q)
                    if "filters" in q_wire:
                        q_wire["filters"] = normalize_host_for_wire(q_wire["filters"], own_iid)
                    payload = {
                        "chart_id": row["chart_id"],
                        "name": row["name"],
                        "query": q_wire,
                        "window_minutes": int(row["window_minutes"]),
                        "comparator": row["comparator"],
                        "threshold": float(row["threshold"]),
                        "for_minutes": int(row["for_minutes"]),
                        "cooldown_minutes": int(row["cooldown_minutes"]),
                        "enabled": bool(row["enabled"]),
                    }
                    key = f"st:{tid}"
                    if workspace_kind.valid(key, payload):
                        records[key] = payload
                        tripwire_ids.add(tid)

            if table_exists(db, "stats_annotations"):
                for row in db.execute(
                    "SELECT id, occurred_at, kind, label, scope_json, rule_hash, reference, basis "
                    "FROM stats_annotations ORDER BY id"
                ):
                    aid = str(row["id"])
                    try:
                        raw_scope = json.loads(row["scope_json"])
                    except ValueError:
                        raw_scope = {}
                    payload = {
                        "occurred_at": int(row["occurred_at"]),
                        "kind": row["kind"],
                        "label": row["label"],
                        "scope": normalize_host_for_wire(raw_scope, own_iid) if isinstance(raw_scope, dict) else {},
                        "rule_hash": row["rule_hash"],
                        "reference": row["reference"],
                        "basis": row["basis"],
                    }
                    key = f"sa:{aid}"
                    if workspace_kind.valid(key, payload):
                        records[key] = payload
                        ann_ids.add(aid)

            if table_exists(db, "stats_settings"):
                srow = db.execute("SELECT enabled FROM stats_settings WHERE singleton=1").fetchone()
                if srow is not None:
                    sval = {"enabled": bool(srow["enabled"])}
                    if workspace_kind.valid("ss:settings", sval):
                        records["ss:settings"] = sval
    except sqlite3.Error as exc:
        log.warning("mesh_workspace_stats_collect_failed", error=type(exc).__name__)
        return {}, set(), set(), set()

    return records, chart_ids, tripwire_ids, ann_ids


def _apply_charts(db: sqlite3.Connection, rows: Rows, held: Set[str], own_iid: str, seen: Any) -> bool:
    if not table_exists(db, "stats_charts"):
        return False
    existing = {str(r["id"]): r["config_json"] for r in db.execute("SELECT id, config_json FROM stats_charts")}
    changed = False
    now = int(time.time())
    for key, (val, _stamp) in rows.items():
        if not key.startswith("sc:") or key in held:
            continue
        cid = key[3:]
        if workspace_kind.is_tomb(val):
            if cid in existing:
                db.execute("DELETE FROM stats_charts WHERE id=?", (cid,))
                changed = True
            seen.scalars[key] = TOMB_HASH
            seen.known_charts.discard(cid)
            continue
        if not isinstance(val, dict):
            continue
        local_cfg = _normalize_chart_hosts(val, own_iid, for_wire=False)
        try:
            validated = ChartWrite.model_validate(local_cfg)
        except ValidationError as exc:
            log.warning("mesh_workspace_stats_chart_invalid", chart_id=cid, error=str(exc)[:120])
            continue
        cfg_json = validated.model_dump_json(by_alias=True, exclude={"id"})
        cur_parsed = None
        if cid in existing:
            try:
                cur_parsed = json.loads(existing[cid])
            except ValueError:
                cur_parsed = None
        new_parsed = json.loads(cfg_json)
        if cur_parsed != new_parsed:
            if cid in existing:
                db.execute(
                    "UPDATE stats_charts SET revision=revision+1, config_json=?, updated_at=? WHERE id=?",
                    (cfg_json, now, cid),
                )
            else:
                db.execute(
                    "INSERT INTO stats_charts (id, revision, config_json, created_at, updated_at) VALUES (?, 1, ?, ?, ?)",
                    (cid, cfg_json, now, now),
                )
            changed = True
        seen.scalars[key] = value_hash(_normalize_chart_hosts(new_parsed, own_iid, for_wire=True))
        seen.known_charts.add(cid)
    return changed


def _apply_tripwires(db: sqlite3.Connection, rows: Rows, held: Set[str], own_iid: str, seen: Any) -> bool:
    if not table_exists(db, "stats_tripwires"):
        return False
    existing = {
        str(r["id"]): (
            r["chart_id"], r["name"], r["query"], int(r["window_minutes"]),
            r["comparator"], float(r["threshold"]), int(r["for_minutes"]),
            int(r["cooldown_minutes"]), bool(r["enabled"]),
        )
        for r in db.execute(
            "SELECT id, chart_id, name, query, window_minutes, comparator, threshold, "
            "for_minutes, cooldown_minutes, enabled FROM stats_tripwires"
        )
    }
    changed = False
    now = int(time.time())
    for key, (val, _stamp) in rows.items():
        if not key.startswith("st:") or key in held:
            continue
        tid = key[3:]
        if workspace_kind.is_tomb(val):
            if tid in existing:
                db.execute("DELETE FROM stats_tripwires WHERE id=?", (tid,))
                changed = True
            seen.scalars[key] = TOMB_HASH
            seen.known_tripwires.discard(tid)
            continue
        if not isinstance(val, dict):
            continue
        local_val = dict(val)
        if isinstance(local_val.get("query"), dict) and "filters" in local_val["query"]:
            q_copy = dict(local_val["query"])
            q_copy["filters"] = normalize_host_for_local(q_copy["filters"], own_iid)
            local_val["query"] = q_copy
        try:
            validated = TripwireWrite.model_validate(local_val)
        except ValidationError as exc:
            log.warning("mesh_workspace_stats_tripwire_invalid", tripwire_id=tid, error=str(exc)[:120])
            continue
        q_json = json.dumps(validated.query, sort_keys=True, separators=(",", ":"))
        chart_id_str = str(validated.chart_id) if validated.chart_id else None
        desired = (
            chart_id_str, validated.name, q_json, validated.window_minutes, validated.comparator,
            float(validated.threshold), validated.for_minutes, validated.cooldown_minutes, bool(validated.enabled),
        )
        if existing.get(tid) != desired:
            if tid in existing:
                db.execute(
                    "UPDATE stats_tripwires SET chart_id=?, name=?, query=?, window_minutes=?, comparator=?, "
                    "threshold=?, for_minutes=?, cooldown_minutes=?, enabled=?, state='unknown', since=?, "
                    "pending_since=NULL, last_fired_at=NULL, last_value=NULL WHERE id=?",
                    (
                        chart_id_str, validated.name, q_json, validated.window_minutes, validated.comparator,
                        validated.threshold, validated.for_minutes, validated.cooldown_minutes,
                        int(validated.enabled), now, tid,
                    ),
                )
            else:
                db.execute(
                    "INSERT INTO stats_tripwires(id, chart_id, name, query, window_minutes, comparator, "
                    "threshold, for_minutes, cooldown_minutes, enabled, state, since, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown', ?, ?)",
                    (
                        tid, chart_id_str, validated.name, q_json, validated.window_minutes, validated.comparator,
                        validated.threshold, validated.for_minutes, validated.cooldown_minutes,
                        int(validated.enabled), now, now,
                    ),
                )
            changed = True
        q_wire = dict(validated.query)
        if "filters" in q_wire:
            q_wire["filters"] = normalize_host_for_wire(q_wire["filters"], own_iid)
        wire_payload = {
            "chart_id": chart_id_str, "name": validated.name, "query": q_wire,
            "window_minutes": validated.window_minutes, "comparator": validated.comparator,
            "threshold": float(validated.threshold), "for_minutes": validated.for_minutes,
            "cooldown_minutes": validated.cooldown_minutes, "enabled": bool(validated.enabled),
        }
        seen.scalars[key] = value_hash(wire_payload)
        seen.known_tripwires.add(tid)
    return changed


def _apply_annotations(db: sqlite3.Connection, rows: Rows, held: Set[str], own_iid: str, seen: Any) -> bool:
    if not table_exists(db, "stats_annotations"):
        return False
    existing = {
        str(r["id"]): (
            int(r["occurred_at"]), r["kind"], r["label"], r["scope_json"],
            r["rule_hash"], r["reference"], r["basis"],
        )
        for r in db.execute(
            "SELECT id, occurred_at, kind, label, scope_json, rule_hash, reference, basis FROM stats_annotations"
        )
    }
    changed = False
    now = int(time.time())
    for key, (val, _stamp) in rows.items():
        if not key.startswith("sa:") or key in held:
            continue
        aid = key[3:]
        if workspace_kind.is_tomb(val):
            if aid in existing:
                db.execute("DELETE FROM stats_annotations WHERE id=?", (aid,))
                changed = True
            seen.scalars[key] = TOMB_HASH
            seen.known_annotations.discard(aid)
            continue
        if not isinstance(val, dict):
            continue
        ts = val.get("occurred_at")
        if not isinstance(ts, int) or isinstance(ts, bool):
            continue
        scope_local = normalize_host_for_local(val.get("scope") or {}, own_iid)
        try:
            validated = AnnotationWrite.model_validate({
                "occurred_at": datetime.fromtimestamp(ts, timezone.utc),
                "kind": val.get("kind", "manual"),
                "label": val.get("label"),
                "scope": scope_local,
                "rule_hash": val.get("rule_hash"),
                "reference": val.get("reference"),
                "basis": val.get("basis", "manual"),
            })
        except (ValidationError, ValueError, OSError) as exc:
            log.warning("mesh_workspace_stats_annotation_invalid", ann_id=aid, error=str(exc)[:120])
            continue
        scope_json = validated.scope.model_dump_json(exclude_none=True)
        occ_int = int(validated.occurred_at.timestamp())
        cur = existing.get(aid)
        cur_same = False
        if cur is not None:
            try:
                cur_scope = json.loads(cur[3])
            except ValueError:
                cur_scope = None
            cur_same = (
                cur[0] == occ_int and cur[1] == validated.kind and cur[2] == validated.label
                and cur_scope == json.loads(scope_json) and cur[4] == validated.rule_hash
                and cur[5] == validated.reference and cur[6] == validated.basis
            )
        if not cur_same:
            if aid in existing:
                db.execute(
                    "UPDATE stats_annotations SET revision=revision+1, occurred_at=?, kind=?, label=?, "
                    "scope_json=?, rule_hash=?, reference=?, basis=?, updated_at=? WHERE id=?",
                    (occ_int, validated.kind, validated.label, scope_json, validated.rule_hash,
                     validated.reference, validated.basis, now, aid),
                )
            else:
                db.execute(
                    "INSERT INTO stats_annotations (id, revision, occurred_at, kind, label, scope_json, "
                    "rule_hash, reference, basis, created_at, updated_at) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (aid, occ_int, validated.kind, validated.label, scope_json, validated.rule_hash,
                     validated.reference, validated.basis, now, now),
                )
            changed = True
        wire_payload = {
            "occurred_at": occ_int, "kind": validated.kind, "label": validated.label,
            "scope": normalize_host_for_wire(json.loads(scope_json), own_iid),
            "rule_hash": validated.rule_hash, "reference": validated.reference, "basis": validated.basis,
        }
        seen.scalars[key] = value_hash(wire_payload)
        seen.known_annotations.add(aid)
    return changed


def apply_stats(
    stats_store: Optional[Any], rows: Rows, held: Set[str], own_iid: str, seen: Any
) -> Tuple[bool, Optional[int], Optional[Dict[str, Any]]]:
    if stats_store is None or not Path(stats_store.db_path).exists():
        return False, None, None

    changed = False
    settings_result: Optional[Dict[str, Any]] = None
    try:
        with stats_store.connect() as db:
            c_changed = _apply_charts(db, rows, held, own_iid, seen)
            t_changed = _apply_tripwires(db, rows, held, own_iid, seen)
            a_changed = _apply_annotations(db, rows, held, own_iid, seen)
            if c_changed or t_changed or a_changed:
                changed = True
                if table_exists(db, "stats_meta"):
                    stats_config._bump(db)

        if "ss:settings" in rows and "ss:settings" not in held:
            sval = rows["ss:settings"][0]
            if isinstance(sval, dict) and isinstance(sval.get("enabled"), bool):
                cur_settings = stats_config.get_settings(stats_store)
                if cur_settings["enabled"] != sval["enabled"]:
                    settings_result = stats_config.update_settings(
                        stats_store, enabled=sval["enabled"], revision=cur_settings["revision"]
                    )
                    changed = True
                seen.scalars["ss:settings"] = value_hash({"enabled": sval["enabled"]})

        rev = stats_store.revision() if changed else None
    except (sqlite3.Error, stats_config.RevisionConflict) as exc:
        log.warning("mesh_workspace_stats_apply_failed", error=type(exc).__name__)
        return False, None, None

    return changed, rev, settings_result
