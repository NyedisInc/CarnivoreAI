
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from src.core.lineage import constants as K
from src.core.lineage import graph

META_BYTES: int = 262144
HUMAN_SOURCES = ("cli", "vscode")
HEADLESS_SOURCES = ("exec", "mcp")
SOURCE_SUBAGENT_LABEL = "subagent"


@dataclass(frozen=True)
class CodexMeta:

    conversation_id: str
    forked_from: Optional[str]
    spawn_parent: Optional[str]
    entrypoint: Optional[str]
    level: Optional[str]


def rollouts(sessions_root: Path) -> Iterator[Path]:
    if sessions_root.is_dir():
        yield from sorted(sessions_root.rglob("rollout-*.jsonl"))


def _find_key(node: Any, key: str) -> Optional[str]:
    if isinstance(node, dict):
        if isinstance(node.get(key), str) and node[key]:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found:
                return found
    return None


def parse_meta(conversation_id: str, payload: Dict[str, Any]) -> CodexMeta:
    source = payload.get("source")
    forked = payload.get("forked_from_id") if isinstance(payload.get("forked_from_id"), str) else None
    parent = _find_key(source, "parent_thread_id") if isinstance(source, dict) else None
    if isinstance(source, str):
        entrypoint = source
    else:
        entrypoint = SOURCE_SUBAGENT_LABEL if isinstance(source, dict) and "subagent" in source else None
    if parent or entrypoint == SOURCE_SUBAGENT_LABEL or source in HEADLESS_SOURCES:
        level = K.LEVEL_SUBSESSION
    else:
        level = K.LEVEL_HUMAN if source in HUMAN_SOURCES else None
    return CodexMeta(conversation_id, forked if forked != conversation_id else None, parent, entrypoint, level)


def read_meta(path: Path) -> Optional[CodexMeta]:
    from src.core.codex_corpus_discover import codex_conversation_id

    conversation = codex_conversation_id(path.name)
    if conversation is None:
        return None
    with path.open("rb") as handle:
        line = handle.readline(META_BYTES)
    try:
        record = json.loads(line)
    except ValueError:
        return None
    payload = record.get("payload") if isinstance(record, dict) and record.get("type") == "session_meta" else None
    return parse_meta(conversation, payload) if isinstance(payload, dict) else None


def apply_meta(conn: sqlite3.Connection, meta: CodexMeta, session_of: Dict[str, str]) -> Counter:
    out: Counter = Counter()
    conv = meta.conversation_id
    out["nodes"] += graph.set_node(conn, K.NODE_CONVERSATION, conv, meta.level, meta.entrypoint)
    detail = {K.DETAIL_EVIDENCE: K.EVIDENCE_FORKED_FROM, "agent_family": "codex"}
    if meta.forked_from:
        out["codex_fork_edges"] += graph.add_edge(
            conn, K.NODE_CONVERSATION, meta.forked_from, K.NODE_CONVERSATION, conv, K.KIND_FORK,
            detail={**detail, K.DETAIL_SPLIT_SESSION: meta.forked_from}) == "added"
        if session_of.get(conv):
            graph.add_edge(conn, K.NODE_CONVERSATION, meta.forked_from, K.NODE_SESSION, session_of[conv], K.KIND_FORK,
                           detail={**detail, K.DETAIL_SPLIT_SESSION: meta.forked_from})
    if meta.spawn_parent:
        out["codex_spawn_edges"] += graph.add_edge(
            conn, K.NODE_CONVERSATION, meta.spawn_parent, K.NODE_CONVERSATION, conv, K.KIND_SPAWNED_BY,
            detail={"agent_family": "codex", K.DETAIL_EVIDENCE: "thread_spawn"}) == "added"
    return out
