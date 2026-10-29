
from __future__ import annotations

from typing import Tuple

FORMAT: str = "carnivore-crate"
FORMAT_MAJOR: int = 1
FORMAT_MINOR: int = 1
FORMAT_MINOR_BASE: int = 0
MAGIC: bytes = b"carnivore-crate 1\n"
AGE_MAGIC: bytes = b"age-encryption.org/v1\n"

M_MAGIC: str = "CRATE"
M_README: str = "README.txt"
M_EXTRACT: str = "extract.py"
M_MANIFEST: str = "crate.json"
M_FILES: str = "files.jsonl"
M_PATHS: str = "paths.jsonl"
M_ENTRIES: str = "entries.json"
M_SECRETS: str = "secrets.json"
M_RECONCILE: str = "reconcile.json"
M_SCHEMA: str = "rows/schema.json"
M_PROJECT_PATCH: str = "project/uncommitted.patch"
ROWS_PREFIX: str = "rows/"
LINES_PREFIX: str = "lines/"
BLOBS_PREFIX: str = "blobs/"

CONTENT_ID_MEMBERS: Tuple[str, ...] = (M_FILES, M_PATHS, M_ENTRIES)

VARIANT_OWN: str = "own"
VARIANT_SHARE: str = "share"
VARIANTS: Tuple[str, ...] = (VARIANT_OWN, VARIANT_SHARE)

HOME_CLAUDE: str = "claude"
HOME_CODEX: str = "codex"
HOME_STATE: str = "state"
HOME_KINDS: Tuple[str, ...] = (HOME_CLAUDE, HOME_CODEX, HOME_STATE)
HOME_PROJECT: str = "project"
HOME_KINDS_V1_1: Tuple[str, ...] = (HOME_PROJECT,)
HOME_PLUGIN_PREFIX: str = "plugin-"

ROLES: Tuple[str, ...] = (
    "transcript", "subagent", "tool_result", "conversation_file", "file_history", "todo", "memory",
    "orphan_transcript", "codex_rollout", "task_file", "swarm_desk", "plan",
    "set_aside_transcript", "conflict_copy", "archived_copy", "project_note",
)
ROLE_PROJECT_FILE: str = "project_file"
ROLE_PROJECT_LINK: str = "project_link"
ROLE_PLUGIN_FILE: str = "plugin_file"
BACKUPS_DATA: str = "backups"
PROVIDES_BACKUP_POINTS: str = "backup_points"
LEGACY_BACKUPS_PLUGIN: str = "save"
ROLES_V1_1: Tuple[str, ...] = (ROLE_PROJECT_FILE, ROLE_PROJECT_LINK, ROLE_PLUGIN_FILE)
LINE_ROLES: Tuple[str, ...] = ("transcript", "subagent", "codex_rollout", "orphan_transcript", "set_aside_transcript")
LINE_ROLES_WHEN_JSONL: Tuple[str, ...] = ("orphan_transcript", "conflict_copy", "archived_copy")

LINES_SOURCES: Tuple[str, ...] = ("claude-history", "codex-session-index")

RESUME_CLAUDE: str = "claude_resume"
RESUME_FORK_ONLY: str = "fork_only"
RESUME_CODEX: str = "unsupported_codex"

SHARED_ENC: str = "_shared"

MiB: int = 1024 * 1024
MAX_JSON_MEMBER: int = 256 * MiB
ROWS_PART_BYTES: int = 256 * MiB
MAX_ROWS_LINE: int = 256 * MiB
MAX_ROWS_PART: int = ROWS_PART_BYTES + MAX_ROWS_LINE
MAX_MEMBERS: int = 4_000_000
MAX_CHUNK_LENGTH: int = 64 * MiB
MAX_BLOB_MEMBER: int = MAX_CHUNK_LENGTH + MAX_CHUNK_LENGTH // 64 + 64 * 1024
READ_BYTES: int = MiB

TAR_MODE: int = 0o644
UID: int = 0
GID: int = 0

DRILL_SPACE_FACTOR: float = 1.05
