
from __future__ import annotations

from typing import Tuple

TABLE: str = "transcript_files"

FAMILY_CLAUDE: str = "claude"
FAMILY_CODEX: str = "codex"

KIND_CONVERSATION: str = "conversation"
KIND_SUBAGENT: str = "subagent"
KIND_OTHER: str = "other"
KINDS: Tuple[str, ...] = (KIND_CONVERSATION, KIND_SUBAGENT, KIND_OTHER)

STATUS_PRESENT: str = "present"
STATUS_GROWN: str = "grown"
STATUS_REWRITTEN: str = "rewritten"
STATUS_GONE: str = "gone"
STATUSES: Tuple[str, ...] = (STATUS_PRESENT, STATUS_GROWN, STATUS_REWRITTEN, STATUS_GONE)

OUT_ADDED: str = "added"
OUT_UNCHANGED: str = "unchanged"
OUT_GROWN: str = "grown"
OUT_REWRITTEN: str = "rewritten"
OUT_REMOVED: str = "removed"
OUT_DATALESS: str = "dataless"
OUT_UNREADABLE: str = "unreadable"
OUTCOMES: Tuple[str, ...] = (OUT_ADDED, OUT_UNCHANGED, OUT_GROWN, OUT_REWRITTEN, OUT_REMOVED,
                             OUT_DATALESS, OUT_UNREADABLE)

SF_DATALESS: int = 0x40000000

TAIL_WINDOW_BYTES: int = 64 * 1024
TAIL_MAX_BYTES: int = 32 * 1024 * 1024
SERIAL_HASH_PREFIX: str = "sha256:"
SERIAL_HASH_CHARS: int = 32

SCAN_INTERVAL_SECONDS: float = 5 * 60
CONDITION_KEY: str = "transcripts.manifest"
ALERT_SOURCE: str = "transcript_manifest"
REMOVED_ALERT_KEY: str = "transcripts.removed"
RETIRED_FRESHNESS_ALERT_KEY: str = "archive.freshness"
RETIRED_PIPELINE_ALERT_KEYS: tuple = (CONDITION_KEY, "pipeline.llm_all_down")
RETIRED_PIPELINE_ALERT_PREFIXES: tuple = ("pipeline.stage_dead.", "backup_health.plugin.")

DEFAULT_LIST_LIMIT: int = 100
MAX_LIST_LIMIT: int = 1000
