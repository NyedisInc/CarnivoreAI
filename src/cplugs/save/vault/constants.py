
from __future__ import annotations

from typing import Tuple

from src.cplugs.sdk.vault_health import DEFAULT_DIR_NAME, LOCATION_CONFIG_BLOCK, LOCATION_CONFIG_FIELD, LOCATION_SETTING, MANIFESTS_DIR  # noqa: F401
from src.cplugs.sdk.blob_codec import BLOBS_PREFIX

MARKER_NAME: str = "VAULT.json"
FORMAT_VERSION: int = 1
REMOVABLE_PARENT: str = "/Volumes"

BLOBS_DIR: str = BLOBS_PREFIX
STATE_FILE: str = "vault-state.json"
SUMMARIES_FILE: str = "vault-summaries.z"
VERIFIED_FILE: str = "vault-verified.json"
LEGACY_DONE_FILE: str = "legacy-migrated.json"
LEGACY_PINNED_MARKER: str = "pinned"
LEGACY_RETRY_SECONDS: int = 3600

BLOB_TOUCH_SECONDS: int = 3600

CHUNK_KNOWN_SECONDS: float = 600.0
CHUNK_KNOWN_MAX: int = 100_000

FOLDER_MEMO_MAX_ENTRIES: int = 60_000
MANIFEST_MEMO_MAX_ENTRIES: int = 20_000
WORKDIR_MEMO_MAX: int = 4096

SHA_CONTENT: str = "content"
SHA_CHAIN: str = "chain"
DEFAULT_RESTORE_MODE: int = 0o600

ROLE_TRANSCRIPT: str = "transcript"
ROLE_SUBAGENT: str = "subagent"
ROLE_TOOL_RESULT: str = "tool_result"
ROLE_CONVERSATION_OTHER: str = "conversation_file"
ROLE_FILE_HISTORY: str = "file_history"
ROLE_MEMORY: str = "memory"
ROLE_CODEX_ROLLOUT: str = "codex_rollout"
ROLE_SIDE_DB: str = "side_db"
ROLE_FOLDER_FILE: str = "folder_file"
QUIET_TAIL_SECONDS: float = 300.0
LINE_ROLES: Tuple[str, ...] = (ROLE_TRANSCRIPT, ROLE_SUBAGENT, ROLE_CODEX_ROLLOUT)
MAIN_ROLES: Tuple[str, ...] = (ROLE_TRANSCRIPT, ROLE_CODEX_ROLLOUT)

REASON_KILL: str = "kill"
REASON_REMOVE: str = "remove"
REASON_SLEEP: str = "sleep"
REASON_RESTART: str = "restart"
REASON_BACKFILL: str = "backfill"
REASON_FOLLOW: str = "follow"
REASON_LEGACY: str = "legacy"
LIFECYCLE_REASONS: Tuple[str, ...] = (REASON_KILL, REASON_REMOVE, "clear", "fork", "resume", "switch")
ROTATING_REASONS: Tuple[str, ...] = (REASON_FOLLOW, REASON_BACKFILL, REASON_LEGACY, REASON_SLEEP, REASON_RESTART)

SIDE_DB_UNIT: str = "side-databases"
MEMORY_UNIT_PREFIX: str = "memory@"
KIND_FOLDER: str = "folder"
KIND_CONVERSATION: str = "conversation"
FAMILY_PLUGIN: str = "plugin"
FOLDER_SKIP_SUFFIXES: Tuple[str, ...] = (".lock",)
FOLDER_SKIP_NAMES: Tuple[str, ...] = (".DS_Store",)
FOLDER_SKIP_DIRS: Tuple[str, ...] = ("__pycache__", ".cache", ".pytest_cache", ".mypy_cache")
FOLDER_READ_LAST: Tuple[str, ...] = (".git/objects/",)
RESTORED_SUFFIX: str = ".restored-"

MAX_POINTS_PER_UNIT: int = 10
DEFAULT_HISTORY_CAP_BYTES: int = 8 * 1024 ** 3
GC_GRACE_SECONDS: int = 6 * 3600
PINNED_SUFFIX: str = ".pinned"
KEPT_SUFFIX: str = ".keep"
TAGS_SUFFIX: str = ".tags"
REASON_IMPORT: str = "import"
EXPORTED_MARKER: str = "EXPORTED"

FOLLOW_SECONDS: int = 10 * 60
BACKFILL_RETRY_SECONDS: int = 2
SLICE_SECONDS: float = 20.0
DUTY_CYCLE: float = 0.35
STABLE_READ_TRIES: int = 3


RANGE_CACHE_CHUNKS: int = 8
