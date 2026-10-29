
from __future__ import annotations

from typing import Dict, Tuple

EDGES_TABLE: str = "lineage_edges"
NODES_TABLE: str = "lineage_nodes"
SOURCES_TABLE: str = "lineage_sources"
MILESTONES_TABLE: str = "conversation_milestones"

NODE_SESSION: str = "session"
NODE_CONVERSATION: str = "conversation"
NODE_SUBAGENT: str = "subagent"
NODE_TYPES: Tuple[str, ...] = (NODE_SESSION, NODE_CONVERSATION, NODE_SUBAGENT)

LEVEL_HUMAN: str = "human"
LEVEL_SUBSESSION: str = "subsession"
LEVEL_AGENT: str = "agent"
NODE_LEVELS: Tuple[str, ...] = (LEVEL_HUMAN, LEVEL_SUBSESSION, LEVEL_AGENT)
LEVEL_BY_ENTRYPOINT: Dict[str, str] = {
    "cli": LEVEL_HUMAN, "claude-desktop": LEVEL_HUMAN,
    "sdk-cli": LEVEL_SUBSESSION, "sdk-ts": LEVEL_SUBSESSION, "sdk-py": LEVEL_SUBSESSION,
}

KIND_CLEAR: str = "clear"
KIND_FORK: str = "fork"
KIND_RESUME: str = "resume"
KIND_SWITCH: str = "switch"
KIND_COMPACT_CONTINUE: str = "compact_continue"
KIND_SUBAGENT: str = "subagent"
KIND_SPAWNED_BY: str = "spawned_by"
KIND_REWIND: str = "rewind"
EDGE_KINDS: Tuple[str, ...] = (KIND_CLEAR, KIND_FORK, KIND_RESUME, KIND_SWITCH, KIND_COMPACT_CONTINUE,
                               KIND_SUBAGENT, KIND_SPAWNED_BY, KIND_REWIND)
CONTINUATION_KINDS: Tuple[str, ...] = (KIND_CLEAR, KIND_FORK, KIND_RESUME, KIND_SWITCH, KIND_COMPACT_CONTINUE,
                                       KIND_REWIND)

EDGE_KIND_BY_REASON: Dict[str, str] = {
    "clear": KIND_CLEAR, "reset": KIND_CLEAR, "new": KIND_CLEAR,
    "fork": KIND_FORK, "resume": KIND_RESUME, "switch": KIND_SWITCH,
}

BASIS_RECORDED: str = "recorded"
BASIS_INFERRED_FORK_POINTER: str = "inferred_fork_pointer"
BASIS_INFERRED_UNIQUE_CANDIDATE: str = "inferred_unique_candidate"
BASIS_INFERRED_ACTIVE_SESSION: str = "inferred_active_session"
LINK_BASES: Tuple[str, ...] = (BASIS_RECORDED, BASIS_INFERRED_FORK_POINTER, BASIS_INFERRED_UNIQUE_CANDIDATE,
                               BASIS_INFERRED_ACTIVE_SESSION)

DETAIL_SPLIT_SESSION: str = "forked_from_session"
DETAIL_SPLIT_MESSAGE: str = "forked_from_message_uuid"
DETAIL_COPY_LINE: str = "line"
DETAIL_EVIDENCE: str = "evidence"
EVIDENCE_COMMAND_RECORD: str = "command_record"
EVIDENCE_FORKED_FROM: str = "forked_from_pointer"
EVIDENCE_ROUTE: str = "route"
DETAIL_VIA: str = "via"
VIA_BOOKMARK_BRANCH: str = "bookmark_branch"
VIA_BOOKMARK_REWIND: str = "bookmark_rewind"

MILESTONE_KINDS: Tuple[str, ...] = ("compact", "clear", "fork", "rewind", "resume", "restart", "sleep", "kill",
                                    "save", "remove", "switch")
MILESTONE_COMPACT: str = "compact"
SOURCE_PIPELINE: str = "pipeline"
SOURCE_JSONL_SCAN: str = "jsonl_scan"
SOURCE_BACKFILL: str = "backfill"
SOURCE_ARCHIVE: str = "archive"
MILESTONE_SOURCES: Tuple[str, ...] = (SOURCE_PIPELINE, SOURCE_JSONL_SCAN, SOURCE_BACKFILL, SOURCE_ARCHIVE)

COMPACT_SUBTYPE: str = "compact_boundary"
SCAN_CHUNK_BYTES: int = 4 * 1024 * 1024
RESUME_ANCHOR_BYTES: int = 4096
HEAD_BYTES: int = 65536
HEAD_RECORDS: int = 40
SUBAGENT_TOOLS: Tuple[str, ...] = ("Task", "Agent")
ARCHIVE_OPEN_ATTEMPTS: int = 10
ARCHIVE_OPEN_DELAY_SECONDS: float = 3.0
SUBAGENTS_DIRNAME: str = "subagents"
