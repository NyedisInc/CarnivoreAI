
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.core.lineage import constants as K
from src.core.lineage import graph, headless, milestones, scan

EdgeRow = Tuple[str, str, str, str, str, str, Optional[str], Optional[Dict[str, Any]]]


@dataclass
class Plan:

    nodes: List[Tuple[str, str, Optional[str], Optional[str]]] = field(default_factory=list)
    edges: List[EdgeRow] = field(default_factory=list)
    compacts: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)


def _iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_disk(out: "Plan", report: scan.ScanReport) -> None:
    for head in report.heads:
        if head.level or head.entrypoint:
            out.nodes.append((K.NODE_CONVERSATION, head.conversation_id, head.level, head.entrypoint))
    for conversation_id, subagent_id in report.subagents:
        out.edges.append((K.NODE_CONVERSATION, conversation_id, K.NODE_SUBAGENT, subagent_id, K.KIND_SUBAGENT,
                          K.BASIS_RECORDED, None, None))
    for hit in report.compacts:
        out.compacts.append({"conversation_id": hit.conversation_id, "at_ts": hit.at_ts, "jsonl_line": hit.line,
                             "jsonl_offset": hit.offset, "detail": hit.detail, "source": K.SOURCE_JSONL_SCAN})
    out.counts.update({"disk_transcripts": report.transcripts, "disk_dataless_skipped": report.dataless_skipped,
                       "disk_unreadable": report.unreadable, "disk_subagent_transcripts": len(report.subagents)})


def plan(conn: sqlite3.Connection, *, disk_roots: Optional[tuple] = None) -> Plan:
    out = Plan()
    heads: List[headless.Head] = []
    if disk_roots is not None:
        report = scan.scan(disk_roots)
        _from_disk(out, report)
        heads += report.heads
    session_of = scan.session_of_conversation(conn)
    for c in out.compacts:
        c["session_uuid"] = session_of.get(c["conversation_id"])
    spawned = scan.spawned_sessions(conn)
    for parent, child, created in spawned:
        out.edges.append((K.NODE_SESSION, parent, K.NODE_SESSION, child, K.KIND_SPAWNED_BY, K.BASIS_RECORDED,
                          created, None))
    started = {h.conversation_id: h.started for h in heads}
    inferred = headless.infer_spawns(heads, session_of)
    for parent_type, parent_id, child in inferred.edges:
        out.edges.append((parent_type, parent_id, K.NODE_CONVERSATION, child, K.KIND_SPAWNED_BY,
                          K.BASIS_INFERRED_ACTIVE_SESSION, _iso(started.get(child)), None))
    out.counts.update({
        "levels_known": sum(1 for n in out.nodes if n[2]),
        "headless_conversations": sum(1 for h in heads if h.level == K.LEVEL_SUBSESSION),
        "headless_linked_inferred": len(inferred.edges), "headless_ambiguous": inferred.ambiguous,
        "headless_no_candidate": inferred.no_candidate, "sessions_spawned_recorded": len(spawned),
        "compact_boundaries": len(out.compacts),
    })
    return out


def edge_counts(edges: List[EdgeRow]) -> Dict[str, int]:
    distinct = {e[:5]: e[5] for e in edges}
    return dict(sorted(Counter(f"{key[4]}/{basis}" for key, basis in distinct.items()).items()))


def _edge_present(conn: sqlite3.Connection, edge: EdgeRow) -> bool:
    row = conn.execute(f"SELECT link_basis FROM {K.EDGES_TABLE} WHERE parent_type = ? AND parent_id = ? "
                       "AND child_type = ? AND child_id = ? AND edge_kind = ?", edge[:5]).fetchone()
    return row is not None and (row[0] == K.BASIS_RECORDED or row[0] == edge[5])


def pending(conn: sqlite3.Connection, edges: List[EdgeRow], compacts: List[Dict[str, Any]]) -> Dict[str, int]:
    distinct = {e[:5]: e for e in edges}
    lines = {(c["conversation_id"], c["jsonl_line"]) for c in compacts}
    if not graph.ready(conn):
        return {"edges_planned": len(distinct), "edges_new": len(distinct), "compacts_planned": len(lines),
                "compacts_new": len(lines)}
    new_edges = sum(1 for e in distinct.values() if not _edge_present(conn, e))
    new_compacts = sum(1 for conv, line in lines if conn.execute(
        f"SELECT 1 FROM {K.MILESTONES_TABLE} WHERE conversation_id = ? AND kind = ? AND jsonl_line = ?",
        (conv, K.MILESTONE_COMPACT, line)).fetchone() is None)
    return {"edges_planned": len(distinct), "edges_new": new_edges, "compacts_planned": len(lines),
            "compacts_new": new_compacts}


def apply(conn: sqlite3.Connection, plan_: Plan) -> Dict[str, int]:
    counts: Counter = Counter()
    for node_type, node_id, level, entrypoint in plan_.nodes:
        counts["nodes_written"] += graph.set_node(conn, node_type, node_id, level, entrypoint)
    for parent_type, parent_id, child_type, child_id, kind, basis, created, detail in plan_.edges:
        outcome = graph.add_edge(conn, parent_type, parent_id, child_type, child_id, kind, basis=basis,
                                 created_at=created, detail=detail)
        counts[f"edges_{outcome}"] += 1
    for c in plan_.compacts:
        counts["compacts_added"] += milestones.add_milestone(
            conn, c["conversation_id"], K.MILESTONE_COMPACT, c["source"], session_uuid=c.get("session_uuid"),
            at_ts=c["at_ts"], jsonl_line=c["jsonl_line"], jsonl_offset=c["jsonl_offset"], detail=c["detail"])
    counts.pop("edges_present", None)
    return dict(counts)
