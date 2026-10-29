
from __future__ import annotations

import re
from typing import Tuple

KIND_EXPORT, KIND_VERIFY, KIND_COPY, KIND_IMPORT = "export", "verify", "copy", "import"
STATE_RUNNING, STATE_DONE, STATE_FAILED, STATE_CANCELLED = "running", "done", "failed", "cancelled"
PHASE_PLANNING, PHASE_ROWS, PHASE_ENTRIES, PHASE_LINES, PHASE_FILES = "planning", "rows", "entries", "lines", "files"
PHASE_SEALING, PHASE_VERIFYING, PHASE_REHASHING = "sealing", "verifying", "rehashing"
PHASE_PUBLISHING, PHASE_RECORDING, PHASE_COPYING = "publishing", "recording", "copying"
PHASE_POST, PHASE_CHECKING = "post", "checking"

BUNDLE_ID_FMT: str = "{prefix}-{stamp}-{scope}-{hex8}"
BUNDLE_STAMP_FMT: str = "%Y%m%dT%H%M%SZ"
PREFIX_OWN, PREFIX_SHARE = "crate", "share"

DEFAULT_FOLDER: str = "crates"
SHARE_SUBFOLDER: str = "share"
FOLDER_PRIMARY, FOLDER_SECOND = "primary", "second"
FOLDER_OK, FOLDER_UNAVAILABLE, FOLDER_UNMOUNTED = "ok", "unavailable", "unmounted"
LOCATION_PRESENT, LOCATION_MISSING = "present", "missing"
FOLDER_MODE: int = 0o700
FILE_MODE: int = 0o600

JOBS_DIR: str = "jobs"
EXTRACT_DIR: str = "extract"
IMPORTS_DIR: str = "imports"
UNDO_FILE, RECEIPT_FILE = "undo.jsonl", "receipt.json"

DUTY: float = 0.5
PROGRESS_NOTIFY_S: float = 2.0
SPACE_FACTOR: float = 1.1
MiB: int = 1024 * 1024
SPACE_RESERVE_BYTES: int = 512 * MiB
ROW_ESTIMATE_BYTES: int = 512
JOB_KEEP_DAYS: int = 30
EXTRACT_KEEP_S: int = 86400
STOP_JOIN_S: float = 4.0
JOBS_LIMIT_DEFAULT, JOBS_LIMIT_MAX = 20, 100
LABEL_MAX: int = 80
DRILL_PREFIX: str = "drill-"
EXTRACT_ID_HEX: int = 6
JOB_ID_RE = re.compile(r"^job-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
E_INTERRUPTED = "interrupted"
E_INTERRUPTED_UNVERIFIED = "interrupted_unverified"
E_JOB_CRASHED = "job_crashed"
E_INTERRUPTED_UNDONE = "interrupted_undone"
E_INTERRUPTED_NEEDS_KEY = "interrupted_needs_key"
E_INTERRUPTED_UNFINISHED = "interrupted_unfinished"
THEME_DOTFILE_MAX_BYTES: int = 4096

HOME_SCRUB_TO: str = "/Users/user"
IMAGE_PLACEHOLDER: str = "[image removed from this shared copy]"

VOLUMES_ROOT: str = "/Volumes"

# conversation id
CRATE_NAME_RE = re.compile(r"^(crate|share)-[A-Za-z0-9._-]{3,90}\.crate(\.age)?$")
UPLOAD_NAME_RE = re.compile(r"^crate-[A-Za-z0-9._-]{3,90}\.crate(\.age)?$")
AGE_MAGIC: bytes = b"age-encryption.org/"
UPLOAD_STALE_S: int = 24 * 3600
CONVERSATION_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,63}$")

B_INVENTORY = "inventory_blocked"
B_LIVE = "session_live"
B_REMOTE = "session_remote"
B_NO_POLICY = "no_crate_policy"
B_FORBIDDEN = "source_forbidden"
B_DATALESS = "source_dataless"
B_MISSING = "conversation_missing"
B_AIR_GAP = "share_air_gapped"
B_FOLDER = "folder_unavailable"
B_SPACE = "no_space"
B_RECIPIENTS = "no_recipients"
B_ROWS = "rows_unreadable"
B_VAULT = "vault_unreachable"
B_VAULT_INCOMPLETE = "vault_incomplete"
B_NOT_TRACED = "file_not_traced"
B_ENTRY = "entry_unreadable"
B_PROJECT_ROOT = "project_root_unavailable"
B_BACKUPS_OFF = "backups_unavailable"
B_BACKUP_FOLDER_OFF, B_BACKUP_FOLDER_UNKNOWN = "backup_folder_unavailable", "backup_folder_unknown"
BLOCKER_CODES: Tuple[str, ...] = (B_INVENTORY, B_LIVE, B_REMOTE, B_NO_POLICY, B_FORBIDDEN, B_DATALESS, B_MISSING,
                                  B_AIR_GAP, B_FOLDER, B_SPACE, B_RECIPIENTS, B_ROWS, B_VAULT, B_VAULT_INCOMPLETE,
                                  B_NOT_TRACED, B_ENTRY, B_PROJECT_ROOT, B_BACKUPS_OFF, B_BACKUP_FOLDER_OFF, B_BACKUP_FOLDER_UNKNOWN)

W_GAP = "store_not_located"
W_OUTSIDE = "outside_scope"
W_FORK_PARENT = "fork_parent_not_carried"
W_CONFLICT = "conflict_copy"
W_ROWS_CHANGED = "rows_changed"
W_PLAN_ABSENT = "plan_file_absent"
W_PATH_JSON = "path_json_unreadable"
W_VAULT_FILE = "carried_from_vault"
W_SECOND_COPY = "second_copy_failed"
W_SYMLINK = "symlink_not_followed"
W_PROJECT_GIT = "project_git_unavailable"
W_PROJECT_PATCH = "project_patch_dropped"

PROJECT_SKIP_NAMES: Tuple[str, ...] = (
    "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".next", ".turbo",
    ".svelte-kit", ".vite", ".gradle", "target", "dist", "build", ".DS_Store", ".git",
)
PROJECT_SKIP_SUFFIXES: Tuple[str, ...] = (".nosync",)
PROJECT_WARN_BYTES: int = 1024 * MiB
PROJECT_SAMPLE_PATHS: int = 5
PROJECT_SKIPPED_LISTED: int = 100
GIT_TIMEOUT_S: float = 60.0
PROJECT_PATCH_MAX_BYTES: int = 64 * MiB
GIT_STATUS_MAX_BYTES: int = 16 * MiB
PROJECT_UNTRACKED_MAX: int = 10_000
