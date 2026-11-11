
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

WORD_ON = "on"
WORD_OFF = "off"
WORD_NEEDS_APPROVAL = "needs_approval"
WORD_HELD = "held"
WORDS = (WORD_ON, WORD_OFF, WORD_NEEDS_APPROVAL, WORD_HELD)

REASON_NEW_INSTALL = "new_install"
REASON_GRANT_WAITING = "grant_waiting"
REASON_CODE_CHANGED = "code_changed"
REASON_CHANGED_ON_DISK = "changed_on_disk"
REASON_SAFE_MODE = "safe_mode"
REASON_THIRD_PARTY_OFF = "third_party_off"
REASON_SIDELOAD_OFF = "sideload_off"
REASON_REVOKED = "revoked"
REASON_INDEX_EXPIRED = "index_expired"
REASON_TRUST_REFUSED = "trust_refused"
REASON_NEEDS_PLUGIN = "needs_plugin"
REASON_FOLDER_UNREADABLE = "folder_unreadable"
REASON_FOLDER_MISSING = "folder_missing"
REASON_MANIFEST_INVALID = "manifest_invalid"
REASON_INSTALL_RECORD_MISSING = "install_record_missing"
REASON_CRASHED = "crashed"
REASON_UNAVAILABLE = "unavailable"
REASON_RUNTIME_DOWN = "runtime_down"

BUTTON_TURN_OFF = "turn_off"
BUTTON_TURN_ON = "turn_on"
BUTTON_REVIEW = "review"
BUTTON_LEAVE_SAFE_MODE = "leave_safe_mode"
BUTTON_TURN_ON_THIRD_PARTY = "turn_on_third_party"
BUTTON_TURN_ON_DEVELOPER = "turn_on_developer"
BUTTON_OPEN_CATALOG = "open_catalog"
BUTTON_TURN_ON_NEEDED = "turn_on_needed_plugin"
BUTTON_SHOW_LOG = "show_log"
BUTTON_DELETE_DATA = "delete_data"

HELD_BUTTONS: Dict[str, str] = {
    REASON_SAFE_MODE: BUTTON_LEAVE_SAFE_MODE,
    REASON_THIRD_PARTY_OFF: BUTTON_TURN_ON_THIRD_PARTY,
    REASON_SIDELOAD_OFF: BUTTON_TURN_ON_DEVELOPER,
    REASON_REVOKED: BUTTON_OPEN_CATALOG,
    REASON_INDEX_EXPIRED: BUTTON_OPEN_CATALOG,
    REASON_NEEDS_PLUGIN: BUTTON_TURN_ON_NEEDED,
    REASON_CRASHED: BUTTON_SHOW_LOG,
    REASON_MANIFEST_INVALID: BUTTON_SHOW_LOG,
    REASON_UNAVAILABLE: BUTTON_SHOW_LOG,
}

KIND_FEATURE = "feature"
KIND_PLUGIN = "plugin"
KIND_CLAUDE_CODE_PLUGIN = "claude_code_plugin"
SOURCE_BUILT_IN = "built_in"
SOURCE_CATALOG = "catalog"
SOURCE_FOLDER = "folder"


@dataclass(frozen=True)
class Verdict:

    word: str
    reason: Optional[str] = None
    button: Optional[str] = None


@dataclass(frozen=True)
class HealthRow:

    id: str
    kind: str
    source: str
    word: str
    reason: Optional[str] = None
    button: Optional[str] = None
    version: Optional[str] = None
    data_bytes: int = 0
    api_version: Optional[int] = None

    def as_wire(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "source": self.source, "word": self.word, "reason": self.reason,
                "button": self.button, "version": self.version, "data_bytes": self.data_bytes, "api_version": self.api_version}


@dataclass(frozen=True)
class OrphanData:

    key: str
    bytes: int
    button: str = BUTTON_DELETE_DATA

    def as_wire(self) -> Dict[str, Any]:
        return {"key": self.key, "bytes": self.bytes, "button": self.button}


@dataclass(frozen=True)
class RemovedInstall:

    name: str
    catalog_id: str
    data_bytes: int
    removed_at: Optional[str] = None
    version: Optional[str] = None

    def as_wire(self) -> Dict[str, Any]:
        return {"name": self.name, "catalog_id": self.catalog_id, "data_bytes": self.data_bytes,
                "removed_at": self.removed_at, "version": self.version}


@dataclass
class HealthReport:

    rows: List[HealthRow] = field(default_factory=list)
    orphan_data: List[OrphanData] = field(default_factory=list)
    removed: List[RemovedInstall] = field(default_factory=list)
    stale_state: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    registry_generation: Optional[int] = None
    registry_source: str = "none"

    def counts(self) -> Dict[str, int]:
        found = {word: 0 for word in WORDS}
        for row in self.rows:
            found[row.word] = found.get(row.word, 0) + 1
        return found

    def as_wire(self) -> Dict[str, Any]:
        return {"counts": self.counts(), "rows": [r.as_wire() for r in self.rows],
                "orphan_data": [o.as_wire() for o in self.orphan_data], "removed": [r.as_wire() for r in self.removed],
                "stale_state": list(self.stale_state), "problems": list(self.problems),
                "registry_generation": self.registry_generation, "registry_source": self.registry_source}
