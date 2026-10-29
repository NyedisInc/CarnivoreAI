
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Optional, Sequence

import structlog

from src.core.lineage import constants as K
from src.core.lineage import graph, scan, split
from src.core.session_conversations import classify

logger = structlog.get_logger()

Finder = Callable[[str, Sequence[Path]], Optional[Path]]


def _evidence(head: classify.Head, reason: str) -> dict:
    if reason in K.EDGE_KIND_BY_REASON and head.command:
        return {K.DETAIL_EVIDENCE: K.EVIDENCE_COMMAND_RECORD, "command": head.command}
    detail = {K.DETAIL_EVIDENCE: K.EVIDENCE_FORKED_FROM}
    if head.forked_from:
        detail[K.DETAIL_SPLIT_SESSION] = head.forked_from
    return detail


def reclassify_switches(conn: sqlite3.Connection, *, roots: Optional[Sequence[Path]] = None,
                        finder: Finder = scan.find_transcript) -> int:
    if not graph.ready(conn):
        return 0
    search = tuple(roots) if roots is not None else scan.roots()
    pairs = conn.execute(
        f"SELECT parent_id, child_id FROM {K.EDGES_TABLE} WHERE edge_kind = ? AND parent_type = ? AND child_type = ?",
        (K.KIND_SWITCH, K.NODE_CONVERSATION, K.NODE_CONVERSATION)).fetchall()
    changed = 0
    for parent, child in pairs:
        path = finder(child, search)
        if path is None:
            continue
        head = classify.read_head(path)
        reason = classify.ended_reason(head, parent)
        kind = K.EDGE_KIND_BY_REASON.get(reason)
        if kind is None or kind == K.KIND_SWITCH:
            continue
        detail = _evidence(head, reason)
        if kind == K.KIND_FORK:
            detail.update(split.split_detail(path))
        targets = [(K.NODE_CONVERSATION, child)] + [
            (K.NODE_SESSION, r[0]) for r in conn.execute(
                f"SELECT child_id FROM {K.EDGES_TABLE} WHERE parent_type = ? AND parent_id = ? AND child_type = ? "
                "AND edge_kind = ?", (K.NODE_CONVERSATION, parent, K.NODE_SESSION, K.KIND_SWITCH))]
        for child_type, child_id in targets:
            changed += graph.retype_edge(conn, K.NODE_CONVERSATION, parent, child_type, child_id,
                                         K.KIND_SWITCH, kind, detail=detail)
        conn.execute(
            f"UPDATE {K.MILESTONES_TABLE} SET kind = ? WHERE conversation_id = ? AND kind = ? "
            "AND json_extract(detail_json, '$.child_conversation_id') = ?", (kind, parent, K.KIND_SWITCH, child))
        logger.info("lineage_switch_reclassified", parent=parent, child=child, kind=kind)
    return changed
