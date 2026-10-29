
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

MODE_SAME = "same_paths"
MODE_RELOCATE = "relocate"
MODES: Tuple[str, ...] = (MODE_SAME, MODE_RELOCATE)

OWN_VERIFIED = "own_verified"
FOREIGN = "foreign"

ACTION_CREATE = "create"
ACTION_ATTACH = "attach"
ACTION_FOLLOW = "follow_uid"

COPY_ROLES: Tuple[str, ...] = ("set_aside_transcript", "conflict_copy", "archived_copy")

CLASS_WRITE = "write"
CLASS_PRESENT = "present"
CLASS_GROW = "grow"
CLASS_LOCAL_NEWER = "local_newer"
CLASS_CONFLICT = "conflict"
CLASS_LIVE = "live"
CLASS_EXCLUDED = "excluded"
CLASS_NOT_RESTORED = "not_restored"
RESUME_NATIVE = "native"
RESUME_FORK = "fork"
RESUME_FILE_ONLY = "file_only"

B_CRATE_NOT_FOUND = "crate_not_found"
B_NEEDS_IDENTITY = "needs_identity"
B_WRONG_KEY = "wrong_key"
B_TOO_NEW = "too_new"
B_VERIFY_FAILED = "verify_failed"
B_PROJECT_CHOICE = "project_choice_needed"
B_RELOCATE_REQUIRED = "relocate_required"
B_ROOT_REFUSED = "root_refused"
B_PROJECT_NOT_HOME = "project_not_home"
B_PROJECT_HOMED_ELSEWHERE = "project_homed_elsewhere"
B_SESSION_LIVE = "session_live"
B_CONVERSATION_LIVE = "conversation_live"
B_PANES_UNKNOWN = "panes_unknown"
B_WRITERS_UNMEASURED = "writers_unmeasured"
B_OFFER_NAMES_SESSION = "offer_names_session"
B_BUSY = "busy"
B_CONFLICT = "conflict"
B_OWNED_ELSEWHERE = "conversation_owned_elsewhere"
B_PATH_OUTSIDE_SCOPE = "path_outside_scope"
B_UNSAFE_DESTINATION = "unsafe_destination"
B_ENC_UNMODELED = "enc_unmodeled"
B_NO_SPACE = "no_space"
B_PLAN_CHANGED = "plan_changed"
B_CPLUG_DISABLED = "cplug_disabled"
B_BAD_MODE = "bad_mode"
B_BAD_REQUEST = "bad_request"
B_SCHEMA_UNREADABLE = "schema_unreadable"
B_BAD_IDENTIFIER = "bad_identifier"
B_NO_SUCH_PROJECT = "no_such_project"
B_JOURNAL_UNREADABLE = "journal_unreadable"
B_CODEC_UNAVAILABLE = "codec_unavailable"
B_CLEANUP_SETTINGS = "cleanup_settings_unreadable"
BLOCKER_CODES: Tuple[str, ...] = (
    B_CRATE_NOT_FOUND, B_NEEDS_IDENTITY, B_WRONG_KEY, B_TOO_NEW, B_VERIFY_FAILED, B_PROJECT_CHOICE,
    B_RELOCATE_REQUIRED, B_ROOT_REFUSED, B_PROJECT_NOT_HOME, B_PROJECT_HOMED_ELSEWHERE, B_SESSION_LIVE, B_CONVERSATION_LIVE,
    B_PANES_UNKNOWN, B_WRITERS_UNMEASURED, B_OFFER_NAMES_SESSION, B_BUSY, B_CONFLICT, B_OWNED_ELSEWHERE, B_PATH_OUTSIDE_SCOPE,
    B_UNSAFE_DESTINATION, B_ENC_UNMODELED, B_NO_SPACE, B_PLAN_CHANGED, B_CPLUG_DISABLED, B_BAD_MODE, B_BAD_REQUEST,
    B_SCHEMA_UNREADABLE, B_BAD_IDENTIFIER, B_NO_SUCH_PROJECT, B_JOURNAL_UNREADABLE,
    B_CODEC_UNAVAILABLE,
    B_CLEANUP_SETTINGS,
)

W_CLAIMS_THIS_COMPUTER = "claims_this_computer"
W_OUTSIDE_MAPPING = "outside_mapping"
W_ENC_UNMAPPED = "enc_unmapped"
W_DANGLING_REF = "dangling_ref"
W_FORK_PARENT_NOT_CARRIED = "fork_parent_not_carried"
W_SESSION_REMINTED = "session_uuid_reminted"
W_AUTOMATION_DISABLED = "automation_disabled"
W_STORE_UNLOCATED = "plugin_store_unlocated"
W_STORE_PLUGIN_OFF = "plugin_store_plugin_off"
W_STORE_NO_FOLDER = "plugin_store_no_folder"
W_PROJECT_RENAMED = "project_renamed"
W_ADOPTION = "adoption"
W_OPEN_OFFER = "open_offer"
W_CLOUD_ONLY = "local_cloud_only"
W_TASK_FILE_KEPT = "task_file_kept"
W_TASK_FILE_FAILED = "task_file_failed"
W_SIDE_STORE_ABSENT = "side_store_absent"
W_ENTRY_NOT_RESTORED = "entry_not_restored"
W_BOARD_UNLINKED = "board_unlinked"
W_LINK_NOT_CREATED = "project_link_not_created"
W_PROJECT_FILE_KEPT = "project_file_kept"
WARNING_CODES: Tuple[str, ...] = (
    W_CLAIMS_THIS_COMPUTER, W_OUTSIDE_MAPPING, W_ENC_UNMAPPED, W_DANGLING_REF, W_FORK_PARENT_NOT_CARRIED, W_SESSION_REMINTED,
    W_AUTOMATION_DISABLED, W_STORE_UNLOCATED, W_STORE_PLUGIN_OFF, W_STORE_NO_FOLDER, W_PROJECT_RENAMED, W_ADOPTION, W_OPEN_OFFER, W_CLOUD_ONLY, W_TASK_FILE_KEPT,
    W_TASK_FILE_FAILED, W_SIDE_STORE_ABSENT, W_ENTRY_NOT_RESTORED, W_BOARD_UNLINKED, W_LINK_NOT_CREATED, W_PROJECT_FILE_KEPT,
)


@dataclass(frozen=True)
class Finding:

    code: str
    detail: str = ""

    def as_json(self) -> Dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class ImportRequest:

    mode: str = MODE_SAME
    new_root: Optional[str] = None
    target_project_id: Optional[int] = None
    skip_conflicts: bool = False
    exclude_conversations: Tuple[str, ...] = ()
    include_project_files: bool = False
    work_in_restored_copy: bool = False
    include_instructions: bool = False
    include_plugin_data: bool = False
    made_here: bool = False
    keep_conversations: bool = False
    file_backups: bool = False
    file_backup_units: Tuple[str, ...] = ()
    rules: Tuple[Tuple[str, str], ...] = ()

    def as_json(self) -> Dict[str, Any]:
        return {"mode": self.mode, "new_root": self.new_root, "target_project_id": self.target_project_id,
                "skip_conflicts": self.skip_conflicts, "exclude_conversations": sorted(self.exclude_conversations),
                "include_project_files": self.include_project_files, "work_in_restored_copy": self.work_in_restored_copy,
                "include_instructions": self.include_instructions, "include_plugin_data": self.include_plugin_data,
                "made_here": self.made_here, "keep_conversations": self.keep_conversations, "file_backups": self.file_backups,
                "file_backup_units": sorted(self.file_backup_units), "rules": [list(r) for r in self.rules]}


@dataclass
class Collector:

    blockers: List[Finding] = field(default_factory=list)
    warnings: List[Finding] = field(default_factory=list)

    def block(self, code: str, detail: str = "") -> None:
        item = Finding(code, detail)
        if item not in self.blockers:
            self.blockers.append(item)

    def warn(self, code: str, detail: str = "") -> None:
        item = Finding(code, detail)
        if item not in self.warnings:
            self.warnings.append(item)


IMPORT_ID_RE = re.compile(r"^imp-\d{8}T\d{6}Z-[0-9a-f]{8}$")

PHASE_ROWS_COMMITTED = "rows_committed"
PHASE_DONE = "done"
PHASE_DONE_WARNINGS = "done_with_warnings"


def new_import_id(now: Optional[float] = None) -> str:
    return f"imp-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(time.time() if now is None else now))}-{secrets.token_hex(4)}"


class ImportRefused(Exception):

    def __init__(self, code: str, detail: str, plan: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.plan = code, detail, plan


class ImportFailed(Exception):

    def __init__(self, code: str, detail: str, *, rolled_back: bool) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.rolled_back = code, detail, rolled_back
