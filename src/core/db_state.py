
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

CANNOT_DETERMINE = "CANNOT_DETERMINE"

VersionValue = Union[int, str]

STATUS_OK = "ok"
STATUS_PAUSED_TRAIL_UNREADABLE = "paused_trail_unreadable"
STATUS_DEGRADED_DB_UNREADABLE = "degraded_db_unreadable"
STATUS_DEGRADED_BACKUP_UNVERIFIED = "degraded_backup_unverified"
STATUS_DEGRADED_SCHEMA_AHEAD = "degraded_schema_ahead"
STATUS_DEGRADED_MIGRATION_FAILED = "degraded_migration_failed"

STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE = "degraded_schema_version_unreadable"

READONLY_STATUSES = (
    STATUS_DEGRADED_DB_UNREADABLE,
    STATUS_DEGRADED_BACKUP_UNVERIFIED,
    STATUS_DEGRADED_SCHEMA_AHEAD,
    STATUS_DEGRADED_MIGRATION_FAILED,
    STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE,
)

TRAIL_STATUS_OK = "ok"
TRAIL_STATUS_ABSENT = "absent"
TRAIL_STATUS_INTERRUPTED = "interrupted"
TRAIL_STATUS_UNREADABLE = "unreadable"
TRAIL_STATUS_PAUSED = "paused"


@dataclass
class DatastoreState:

    status: str
    schema_version: VersionValue
    config_version: VersionValue
    trail_status: str
    code_schema_version: int
    message: str
    detail: Optional[str] = None
    trail_corrupt_line: Optional[int] = None
    failed_entry_uuid: Optional[str] = None
    backup_path: Optional[str] = None
    last_migration_at: Optional[str] = None
    migrations_applied: List[str] = field(default_factory=list)
    db_path: Optional[str] = None
    fresh_install: bool = False

    @property
    def healthy(self) -> bool:
        return self.status == STATUS_OK

    @property
    def readonly(self) -> bool:
        return self.status in READONLY_STATUSES

    @property
    def migrations_paused(self) -> bool:
        return self.readonly or self.status == STATUS_PAUSED_TRAIL_UNREADABLE

    @property
    def restore_offered(self) -> bool:
        return self.trail_status != TRAIL_STATUS_UNREADABLE

    @property
    def reported_trail_status(self) -> str:
        if self.trail_status == TRAIL_STATUS_UNREADABLE:
            return TRAIL_STATUS_UNREADABLE
        if self.migrations_paused:
            return TRAIL_STATUS_PAUSED
        return self.trail_status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "healthy": self.healthy,
            "readonly": self.readonly,
            "migrations_paused": self.migrations_paused,
            "restore_offered": self.restore_offered,
            "schema_version": self.schema_version,
            "schema_version_state": _version_state(self.schema_version),
            "code_schema_version": self.code_schema_version,
            "config_version": self.config_version,
            "config_version_state": _version_state(self.config_version),
            "trail_status": self.reported_trail_status,
            "trail_status_measured": self.trail_status,
            "trail_corrupt_line": self.trail_corrupt_line,
            "last_migration_at": self.last_migration_at,
            "message": self.message,
            "detail": self.detail,
            "failed_entry_uuid": self.failed_entry_uuid,
        }


def _version_state(value: VersionValue) -> str:
    return "known" if isinstance(value, int) else "cannot_determine"
