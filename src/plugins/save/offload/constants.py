
from __future__ import annotations

from typing import Tuple

REASON_LIVE = "live"
REASON_ASLEEP = "asleep"
REASON_REMOTE = "remote"
REASON_UNKNOWN_STATE = "unknown_state"
REASON_IN_USE = "in_use"
REASON_NOT_QUIET = "not_quiet"
REASON_DATALESS = "dataless"
REASON_NO_VAULT_POINT = "no_vault_point"
REASON_VAULT_BEHIND = "vault_behind"
REASON_UNREADABLE_FILE = "unreadable_file"
REASON_NOT_READY = "not_ready"
REASON_NOTHING_ON_DISK = "nothing_on_disk"
REASONS: Tuple[str, ...] = (REASON_LIVE, REASON_ASLEEP, REASON_REMOTE, REASON_UNKNOWN_STATE, REASON_IN_USE, REASON_NOT_QUIET,
                            REASON_DATALESS, REASON_NO_VAULT_POINT, REASON_VAULT_BEHIND, REASON_UNREADABLE_FILE, REASON_NOT_READY, REASON_NOTHING_ON_DISK)

BLOCKER_ICLOUD_PATH = "icloud_path"
BLOCKER_ICLOUD_UNKNOWN = "icloud_unknown"
BLOCKER_REGISTRY_UNREADABLE = "registry_unreadable"

QUIET_SECONDS: float = 24 * 3600.0
DEFAULT_IDLE_DAYS: int = 30
SECONDS_PER_DAY: float = 86400.0

PAGE_DEFAULT: int = 50
PAGE_MAX: int = 200

STATE_OFFLOADING = "offloading"
STATE_OFFLOADED = "offloaded"
STATE_RESTORING = "restoring"
STATE_CONFLICT = "conflict"
STATE_FAILED = "failed"
STATES: Tuple[str, ...] = (STATE_OFFLOADING, STATE_OFFLOADED, STATE_RESTORING, STATE_CONFLICT, STATE_FAILED)

LEDGER_PREV_SUFFIX = ".prev"

HOLDING_DIRNAME = "offload-holding.nobackup"
HOLD_DAYS: int = 7
HOLD_SECONDS: float = HOLD_DAYS * SECONDS_PER_DAY
SCRUB_DAYS: int = 7

CODE_NOT_READY = "not_ready"
CODE_NOT_ELIGIBLE = "not_eligible"
CODE_VERIFY_FAILED = "vault_unverified"
CODE_IN_USE = "in_use"
CODE_BUSY = "offload_busy"
CODE_HOLDING_UNUSABLE = "holding_unusable"
CODE_LEDGER_UNREADABLE = "ledger_unreadable"
CODE_MOVE_FAILED = "move_failed"
CODE_OFFLOAD_DISABLED = "offload_disabled"
OFFLOAD_SETTING = "offloadEnabled"
PUSH_TOPIC = "offload"

BATCH_RUNNING = "running"
BATCH_DONE = "done"
BATCH_STOPPED = "stopped"
BATCH_FAILED = "failed"
ITEM_OFFLOADED = "offloaded"
ITEM_SKIPPED = "skipped"
ITEM_FAILED = "failed"
BATCH_MAX_SESSIONS: int = 5000
CODE_BATCH_BUSY = "batch_busy"
CODE_UNKNOWN_SESSION = "unknown_session"
BATCH_SKIP_CODES: Tuple[str, ...] = (CODE_VERIFY_FAILED, CODE_NOT_ELIGIBLE, CODE_IN_USE, CODE_BUSY, CODE_UNKNOWN_SESSION)

REPAIR_SCRIPT = "scripts/vault/repair-chunks-from-restic.sh"
ALERT_BLOBS_MAX: int = 200

ITEM_RESTORED = "restored"
ITEM_RESTORE_FAILED = "failed"
RESTORE_BATCH_MAX: int = 500
RESTORE_OK_STATUSES: Tuple[str, ...] = ("written", "already_present", "disk_newer")
RESTORE_BUSY_RETRIES: int = 10
RESTORE_BUSY_WAIT_SECONDS: float = 3.0
RESTORE_STOP_CODES: Tuple[str, ...] = ("vault_unavailable", "no_projects_folder")
CODE_BAD_TARGETS = "bad_targets"
