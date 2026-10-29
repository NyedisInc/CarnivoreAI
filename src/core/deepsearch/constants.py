
from __future__ import annotations

from typing import Tuple

from src.core.db_ddl.tables import (  # noqa: F401
    DOC_WATERMARK_COLUMNS,
    DOCS_TABLE,
    FTS_TABLE,
    LIVE_ID_COLUMN,
    LIVE_TABLE,
    MIN_SQLITE,
    ROWS_TABLE,
)

FTS_SHADOW_TABLES: Tuple[str, ...] = tuple(f"{FTS_TABLE}_{part}" for part in ("data", "idx", "docsize", "config"))

CONFIG_BLOCK: str = "save_pipeline"
CONFIG_FIELD: str = "search_filter"

KEEP: str = "keep"
DROP: str = "drop"
MAX_TRUNCATE_CHARS: int = 100_000
VERSION_CHARS: int = 12

KIND_USER: str = "user"
KIND_ASSISTANT: str = "assistant"
KIND_TOOL: str = "tool"
KIND_SUMMARY: str = "summary"
KIND_THINKING: str = "thinking"

SEARCH_LIMIT_DEFAULT: int = 20
SEARCH_LIMIT_MAX: int = 100
SNIPPET_BEFORE: int = 80
SNIPPET_AFTER: int = 160

SKIP_FTS_UNAVAILABLE: str = "fts_unavailable"

LIVE_DOC_ID: int = 0

FILE_CONVERSATION: str = "conversation"
FILE_SUBAGENT: str = "subagent"

MODE_APPEND: str = "append"
MODE_FULL: str = "full"
FULL_FIRST: str = "first_index"
FULL_BEYOND_SIZE: str = "offset_beyond_size"
FULL_HEAD_CHANGED: str = "head_changed"
FULL_FILTER_CHANGED: str = "filter_changed"

SKIP_LIVE_NOTHING_NEW: str = "nothing_new"
SKIP_LIVE_OUT_OF_SCOPE: str = "out_of_scope"

LIVE_DEDUPE_SUFFIX: str = ":live:open"
LIVE_KEEP_DONE_SECONDS: float = 24 * 3600.0
LIVE_WINDOW_SECONDS: float = 15 * 60.0
LIVE_READ_CHUNK: int = 1024 * 1024

CACHE_FILENAME: str = "deepsearch.db"
CACHE_VERSION: int = 2
FOLDERS_TABLE: str = "session_search_folders"
CACHE_META_TABLE: str = "cache_meta"
CACHE_BUILDING: str = "building"
CACHE_READY: str = "ready"
CACHE_SCHEMA: str = "ds"
CACHE_LIVE_REF: str = f"{CACHE_SCHEMA}.{LIVE_TABLE}"
INDEX_SCOPE: str = "all"

VAULT_MARK: str = "vault"
VAULT_LIST_INTERVAL_SECONDS: float = 600.0
VAULT_PASS_BYTES: int = 128 * 1024 * 1024
VAULT_CONFIRM_PER_PASS: int = 200

# state directory
BACKUP_COPY_DIR: str = "deepsearch-backup-copies"
