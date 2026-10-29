
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.cplugs.flow import edges, lanes, participants
from src.cplugs.flow.transcript import Scan, parse_ts, scan_file

logger = structlog.get_logger()

SCHEMA_VERSION = 2
OWNER_LANE = "owner"
IDLE_GAP_S = 600.0
MAX_SAYS = 2000
MAX_CALLS = 6000
ScanFn = Callable[[Path, float, float, str], Scan]


def _label(row: Dict[str, Any]) -> str:
    return str(row.get("title") or row.get("tmux_name") or row["session_uuid"][:8])[:60]


def build_run(activity: Any, seed_kind: str, seed_id: str, *, start: Optional[float] = None, end: Optional[float] = None,
              scan: ScanFn = scan_file, now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    found = participants.resolve(activity, seed_kind, seed_id, start, end, now)
    messages = activity.crosstalk(found.start, found.end)
    participants.walk(found, messages)
    rows = {r["session_uuid"]: r for r in activity.sessions(list(found.reach))}
    out: Dict[str, Any] = {"lanes": [], "blocks": [], "edges": [], "marks": [], "says": [], "calls": [], "warnings": list(found.warnings)}
    scans: Dict[str, List[Scan]] = {}
    order = sorted((u for u in found.reach if u in rows), key=lambda u: (found.reach[u], u))
    for uuid in order:
        row = rows[uuid]
        out["lanes"].append({"id": f"s:{uuid}", "kind": "session", "label": _label(row), "session_uuid": uuid, "app_id": row.get("app_id"),
                             "parent": None, "reach": found.reach[uuid], "working_dir": row.get("working_dir"),
                             "tmux_name": row.get("tmux_name")})
        lo = found.start if found.depth[uuid] == 0 else max(found.start, found.reach[uuid] - participants.REACH_LEAD_S)
        scans[uuid] = _scan_session(activity, uuid, lo, found.end, scan, out)
    for uuid in order:
        lanes.session_blocks(out, f"s:{uuid}", scans[uuid])
        lanes.subagents(out, f"s:{uuid}", scans[uuid], found.start, found.end, scan)
    lane_of = {u: f"s:{u}" for u in order}
    edges.crosstalk_edges(out, messages, lane_of, scans)
    edges.spawn_edges(out, activity, rows, lane_of, scans, found)
    edges.task_manager_events(out, activity, found, lane_of, scans, _mcp_calls(out, activity, rows, lane_of, found))
    _finish(out, found, activity)
    return out


def _scan_session(activity: Any, uuid: str, lo: float, hi: float, scan: ScanFn, out: Dict[str, Any]) -> List[Scan]:
    scans: List[Scan] = []
    for conv in activity.conversations([uuid]):
        if not conv.get("path"):
            continue
        try:
            if _outside(conv, lo, hi):
                continue
            found = scan(Path(conv["path"]), lo, hi, conv["conversation_id"])
        except OSError as exc:
            out["warnings"].append(f"transcript of {conv['conversation_id'][:8]} unreadable: {type(exc).__name__}")
            logger.warning("flow_transcript_unreadable", conversation=conv["conversation_id"], error=str(exc)[:200])
            continue
        if found.records:
            found.path = conv["path"]
            scans.append(found)
    return scans


def _outside(conv: Dict[str, Any], lo: float, hi: float) -> bool:
    try:
        began = parse_ts(conv["started_at"]) if conv.get("started_at") else None
        ended = parse_ts(conv["ended_at"]) if conv.get("ended_at") else None
    except ValueError:
        return False
    return (began is not None and began > hi) or (ended is not None and ended < lo)


def _mcp_calls(out: Dict[str, Any], activity: Any, rows: Dict[str, Dict[str, Any]], lane_of: Dict[str, str],
               found: participants.Participants) -> List[Tuple[str, Dict[str, Any]]]:
    by_caller: Dict[str, str] = {}
    for uuid, row in rows.items():
        by_caller[uuid] = lane_of[uuid]
        if row.get("app_id"):
            by_caller[row["app_id"]] = lane_of[uuid]
    events = activity.mcp_events(list(by_caller), found.start, found.end)
    if events:
        out["mcp_events"] = len(events)
    calls = []
    for e in events:
        ids = {int(n) for blob in (e["target_ids"], e["result_ids"]) for n in re.findall(r"\b\d+\b", blob or "")}
        calls.append((by_caller[e["caller_session_id"]], {"tool": e["tool"], "t": e["started_at"],
                                                          "t_result": e["started_at"] + (e["duration_ms"] or 0) / 1000.0, "item_ids": ids}))
    return calls


def _finish(out: Dict[str, Any], found: participants.Participants, activity: Any) -> None:
    lane_ids = {lane["id"] for lane in out["lanes"]}
    if any(e["from"]["lane"] == OWNER_LANE or e["to"]["lane"] == OWNER_LANE for e in out["edges"]) or any(m["lane"] == OWNER_LANE for m in out["marks"]):
        out["lanes"].insert(0, {"id": OWNER_LANE, "kind": "owner", "label": "owner", "session_uuid": None, "app_id": None, "parent": None})
        lane_ids.add(OWNER_LANE)
    out["edges"] = [e for e in out["edges"] if e["from"]["lane"] in lane_ids and e["to"]["lane"] in lane_ids]
    out["marks"] = [m for m in out["marks"] if m["lane"] in lane_ids]
    out["blocks"] = [b for b in out["blocks"] if b["lane"] in lane_ids]
    says = sorted((s for s in out["says"] if s["lane"] in lane_ids), key=lambda s: (s["t"], s["id"]))
    if len(says) > MAX_SAYS:
        out["warnings"].append(f"kept the newest {MAX_SAYS} of {len(says)} said texts")
    out["says"] = says[-MAX_SAYS:]
    out["calls"] = sorted((c for c in out["calls"] if c["lane"] in lane_ids), key=lambda c: (c["start"], c["id"]))[-MAX_CALLS:]
    ordered = _lane_order(out["lanes"])
    for index, lane in enumerate(ordered):
        lane["order"] = index
    out["lanes"] = ordered
    out["edges"].sort(key=lambda e: (e["from"]["t"], e["id"]))
    out["blocks"].sort(key=lambda b: (b["start"], b["id"]))
    out["marks"].sort(key=lambda m: (m["t"], m["id"]))
    events = [{"t": b["start"], "type": "block", "ref": b["id"]} for b in out["blocks"]]
    events += [{"t": e["from"]["t"], "type": "edge", "ref": e["id"]} for e in out["edges"]]
    events += [{"t": m["t"], "type": "mark", "ref": m["id"]} for m in out["marks"]]
    out["events"] = sorted(events, key=lambda e: (e["t"], e["type"], e["ref"]))
    out["idle_gaps"] = _idle_gaps(out["blocks"], out["edges"], found.start, found.end)
    out["version"] = SCHEMA_VERSION
    out["seed"] = found.seed
    out["window"] = {"start": found.start, "end": found.end}
    out["sources"] = activity.sources()
    inferred = sum(1 for e in out["edges"] if e.get("inferred"))
    kinds: Dict[str, int] = {}
    for e in out["edges"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    out["stats"] = {"lanes": len(out["lanes"]), "blocks": len(out["blocks"]), "edges": len(out["edges"]), "marks": len(out["marks"]),
                    "events": len(out["events"]), "says": len(out["says"]), "inferred_edges": inferred, "edge_kinds": kinds}


def _lane_order(lanes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kids: Dict[str, List[Dict[str, Any]]] = {}
    for lane in lanes:
        if lane["parent"]:
            kids.setdefault(lane["parent"], []).append(lane)
    out: List[Dict[str, Any]] = [lane for lane in lanes if lane["kind"] == "owner"]
    for lane in sorted((x for x in lanes if x["kind"] == "session"), key=lambda x: (x.get("reach") or 0, x["id"])):
        out.append(lane)
        out.extend(sorted(kids.get(lane["id"], []), key=lambda x: (x.get("start") or 0, x["id"])))
    return out


def _idle_gaps(blocks: List[Dict[str, Any]], edges: List[Dict[str, Any]], lo: float, hi: float) -> List[Dict[str, float]]:
    spans: List[Tuple[float, float]] = [(b["start"], b["end"]) for b in blocks if b["kind"] != "tool"]
    spans += [(e["from"]["t"], e["to"]["t"]) for e in edges]
    spans.sort()
    gaps, cursor = [], lo
    for a, b in spans:
        if a - cursor >= IDLE_GAP_S:
            gaps.append({"start": cursor, "end": a})
        cursor = max(cursor, b)
    if hi - cursor >= IDLE_GAP_S:
        gaps.append({"start": cursor, "end": hi})
    return gaps


def dumps(run: Dict[str, Any]) -> str:
    return json.dumps(run, separators=(",", ":"), sort_keys=True)
