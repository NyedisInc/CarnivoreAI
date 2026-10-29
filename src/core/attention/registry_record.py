
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence, Tuple

from src.core.attention.registry_contract import ShapeCheck, check_registry_record
from src.core.subagents.shape_alert import report_unrecognized



REG_OK: str = "ok"

REG_ABSENT: str = "absent"

REG_STALE: str = "stale"

REG_UNREADABLE: str = "unreadable"

REG_SHAPE_UNRECOGNIZED: str = "shape_unrecognized"

STALE_CAUSE_CONVERSATION: str = "conversation"


REG_IDLE: str = "idle"

REG_BUSY: str = "busy"

REG_WAITING: str = "waiting"

REG_SHELL: str = "shell"


MIN_PENDING_VERSION: Tuple[int, int, int] = (2, 1, 241)

MIN_DELEGATED_BUSY_VERSION: Tuple[int, int, int] = (2, 1, 283)

REGISTRY_STALE_AFTER_SECONDS: int = 900



@dataclass(frozen=True)
class RegistryRecord:

    verdict: str

    status: Optional[str]

    waiting_for: Optional[str]

    pid: Optional[int]

    session_uuid: Optional[str]

    tmux_name: Optional[str]

    cwd: Optional[str]

    status_updated_at: Optional[datetime]

    started_at: Optional[datetime]

    version: Optional[Tuple[int, ...]]

    detail: str

    stale_cause: Optional[str] = None

    record_session_uuid: Optional[str] = None

    pane_id: Optional[str] = None

    name: Optional[str] = None

    name_source: Optional[str] = None

    name_since: Optional[datetime] = None

    shape_problems: Tuple[str, ...] = ()
    proc_start: Optional[str] = None
    ambiguous_pane: bool = False

    @property
    def known(self) -> bool:
        return self.verdict == REG_OK

    @property
    def instance_present(self) -> bool:
        return self.known or self.stale_cause == STALE_CAUSE_CONVERSATION

    @property
    def trusts_pending_count(self) -> bool:
        if self.version is None:
            return False
        return self.version >= MIN_PENDING_VERSION

    @property
    def confirms_background_work(self) -> bool:
        if not self.known or self.status != REG_BUSY or self.version is None:
            return False
        return self.version >= MIN_DELEGATED_BUSY_VERSION


def _empty_record(
    verdict: str,
    detail: str,
    *,
    tmux_name: Optional[str] = None,
    stale_cause: Optional[str] = None,
    record_session_uuid: Optional[str] = None,
    shape_problems: Tuple[str, ...] = (),
    ambiguous_pane: bool = False,
) -> RegistryRecord:
    return RegistryRecord(
        verdict=verdict,
        status=None,
        waiting_for=None,
        pid=None,
        session_uuid=None,
        tmux_name=tmux_name,
        cwd=None,
        status_updated_at=None,
        started_at=None,
        version=None,
        detail=detail,
        stale_cause=stale_cause,
        record_session_uuid=record_session_uuid,
        ambiguous_pane=ambiguous_pane,
        shape_problems=tuple(shape_problems),
    )


def tmux_session_of(target: Optional[str]) -> Optional[str]:
    if not isinstance(target, str):
        return None
    head, separator, _tail = target.rpartition(":")
    if not separator:
        return None
    head = head.strip()
    return head or None


def pane_id_of(target: Optional[str]) -> Optional[str]:
    if not isinstance(target, str):
        return None
    _head, separator, tail = target.rpartition(":")
    if not separator:
        return None
    _window, dot, pane = tail.strip().rpartition(".")
    if not dot or not pane.startswith("%") or not pane[1:].isdigit():
        return None
    return pane


def _epoch_millis_to_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_version(value: Any) -> Optional[Tuple[int, ...]]:
    if not isinstance(value, str):
        return None
    parts = value.strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def format_version(version: Sequence[int]) -> str:
    return ".".join(str(part) for part in version)


def _optional_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def parse_registry_record(raw: Any, *, path_pid: Optional[int]) -> RegistryRecord:
    check = check_registry_record(raw)
    if not check.recognized:
        return _shape_refusal(raw, check, path_pid)

    file_pid = raw.get("pid")
    pid: Optional[int]
    pid_note = ""
    if isinstance(file_pid, int) and not isinstance(file_pid, bool):
        pid = file_pid
        if path_pid is not None and path_pid != file_pid:
            pid_note = (
                "pid in the file (%d) disagrees with the filename (%d), "
                "the file wins" % (file_pid, path_pid)
            )
    else:
        pid = path_pid

    if pid is None:
        return _empty_record(
            REG_UNREADABLE,
            "registry file carries no usable pid, in its content or its name",
        )

    status = _optional_text(raw.get("status"))
    if status is None:
        return _empty_record(
            REG_UNREADABLE, "registry file for pid %d carries no status" % pid
        )

    return RegistryRecord(
        verdict=REG_OK,
        status=status,
        waiting_for=_optional_text(raw.get("waitingFor")),
        pid=pid,
        session_uuid=_optional_text(raw.get("sessionId")),
        tmux_name=tmux_session_of(raw.get("tmux")),
        cwd=_optional_text(raw.get("cwd")),
        status_updated_at=_epoch_millis_to_datetime(raw.get("statusUpdatedAt")),
        started_at=_epoch_millis_to_datetime(raw.get("startedAt")),
        version=parse_version(raw.get("version")),
        detail=pid_note,
        pane_id=pane_id_of(raw.get("tmux")),
        name=_optional_text(raw.get("name")),
        name_source=_optional_text(raw.get("nameSource")),
        name_since=_epoch_millis_to_datetime(raw.get("nameSince")),
        proc_start=_optional_text(raw.get("procStart")),
    )


def _shape_refusal(raw: Any, check: ShapeCheck, path_pid: Optional[int]) -> RegistryRecord:
    document = raw if isinstance(raw, dict) else {}
    report_unrecognized(check, claude_code_version=document.get("version"))
    return _empty_record(
        REG_SHAPE_UNRECOGNIZED,
        "registry file %s.json does not match contract %s v%d: %s"
        % (path_pid if path_pid is not None else "?", check.file_kind,
           check.version, "; ".join(check.problems)),
        tmux_name=tmux_session_of(document.get("tmux")),
        shape_problems=check.problems,
    )



def _pid_from_filename(name: str) -> Optional[int]:
    stem = name[: -len(".json")]
    return int(stem) if stem.isdigit() else None



def load_registry_blob(name: str, blob: bytes) -> RegistryRecord:
    try:
        raw = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return _empty_record(REG_UNREADABLE, "cannot parse %s: %s" % (name, exc))

    return parse_registry_record(raw, path_pid=_pid_from_filename(name))

