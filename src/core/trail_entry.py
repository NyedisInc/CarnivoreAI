
from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

REQUIRED_FIELDS: Tuple[str, ...] = ("entry_uuid", "kind", "status", "started_at")

FIELD_ORDER: Tuple[str, ...] = (
    "entry_uuid",
    "kind",
    "from_version",
    "to_version",
    "status",
    "started_at",
    "completed_at",
    "backup_path",
    "backup_verified",
    "app_version",
    "error",
    "detail",
)

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def new_entry_uuid() -> str:
    return str(_uuid.uuid4())


@dataclass
class TrailEntry:

    entry_uuid: str
    kind: str
    status: str
    started_at: str
    from_version: Optional[str] = None
    to_version: Optional[str] = None
    completed_at: Optional[str] = None
    backup_path: Optional[str] = None
    backup_verified: Optional[int] = None
    app_version: Optional[str] = None
    error: Optional[str] = None
    detail: Optional[str] = None
    recovered_partial: bool = field(default=False, compare=False)

    def to_line(self) -> str:
        data = asdict(self)
        data.pop("recovered_partial", None)
        ordered = {k: data[k] for k in FIELD_ORDER}
        return json.dumps(ordered, ensure_ascii=False, separators=(", ", ": ")) + "\n"

    def to_row(self) -> Tuple[Any, ...]:
        return (
            self.entry_uuid,
            self.kind,
            self.from_version,
            self.to_version,
            self.status,
            self.started_at,
            self.completed_at,
            self.backup_path,
            self.backup_verified,
            self.app_version,
            self.error,
            self.detail,
        )

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "TrailEntry":
        return TrailEntry(
            entry_uuid=str(data["entry_uuid"]),
            kind=str(data["kind"]),
            status=str(data["status"]),
            started_at=str(data["started_at"]),
            from_version=_opt_str(data.get("from_version")),
            to_version=_opt_str(data.get("to_version")),
            completed_at=_opt_str(data.get("completed_at")),
            backup_path=_opt_str(data.get("backup_path")),
            backup_verified=_opt_int(data.get("backup_verified")),
            app_version=_opt_str(data.get("app_version")),
            error=_opt_str(data.get("error")),
            detail=_opt_str(data.get("detail")),
        )


def _opt_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _opt_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


