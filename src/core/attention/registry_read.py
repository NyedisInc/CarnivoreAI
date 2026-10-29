
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from src.core.attention.registry_contract import ShapeCheck, check_registry_record
from src.core.attention.registry_file_cache import RegistryFileCache
from src.core.claude_config.profile_roots import claude_registry_roots
from src.core.subagents.shape_alert import report_unrecognized


REG_OK: str = "ok"

REG_ABSENT: str = "absent"

REG_STALE: str = "stale"

# could not
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

REGISTRY_DIRNAME: str = os.path.join(".claude", "sessions")

DEFAULT_SCAN_LIMIT: int = 128

MAX_REGISTRY_FILE_BYTES: int = 64 * 1024

# could not
UNREADABLE_KEY_PREFIX: str = "?unreadable:"


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

    @property
    def known(self) -> bool:
        return self.verdict == REG_OK

    @property
    def instance_present(self) -> bool:
        return self.known or self.stale_cause == STALE_CAUSE_CONVERSATION

    @property
    def trusts_pending_count(self) -> bool:
        """May the transcript's background-agent count be believed?

        Description: the version gate. Below :data:`MIN_PENDING_VERSION`
            the turn-end record carries no ``pendingBackgroundAgentCount``
            at all, so its absence says nothing; a version we could not
            parse is not evidence of a new enough claude. Both answer
            False, sending the resolver to the async ledger instead of to
            a count that is not there.
        Inputs: none beyond ``self``.
        Output: bool - True only for a parsed version at or above the
            floor.
        Example:
            >>> parse_registry_record(
            ...     {"pid": 1, "status": "idle", "version": "2.1.240"},
            ...     path_pid=None).trusts_pending_count
            False
        """
        if self.version is None:
            return False
        return self.version >= MIN_PENDING_VERSION

    @property
    def confirms_background_work(self) -> bool:
        """Does claude's own live record say delegated work is running?

        Description: True only for a known record whose status is ``busy``
            AND whose claude is at or above
            :data:`MIN_DELEGATED_BUSY_VERSION`, where ``busy`` at a resting
            prompt is measured to mean background agents or workflows. A
            refused record, any other status, a lower version and a version
            we could not parse all answer False.
        Inputs: none beyond ``self``.
        Output: bool.
        Example:
            >>> parse_registry_record(
            ...     {"pid": 1, "status": "busy", "version": "2.1.282"},
            ...     path_pid=None).confirms_background_work
            False
        """
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


def pid_is_running(pid: Optional[int]) -> Optional[bool]:
    if pid is None or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # could not
        return None
    return True


def default_registry_directory() -> str:
    return os.path.join(os.path.expanduser("~"), REGISTRY_DIRNAME)


def _pid_from_filename(name: str) -> Optional[int]:
    stem = name[: -len(".json")]
    return int(stem) if stem.isdigit() else None


def _load_registry_file(path: str, name: str) -> RegistryRecord:
    try:
        with open(path, "rb") as handle:
            blob = handle.read(MAX_REGISTRY_FILE_BYTES)
    except OSError as exc:
        return _empty_record(REG_UNREADABLE, "cannot read %s: %s" % (name, exc))
    return load_registry_blob(name, blob)


def load_registry_blob(name: str, blob: bytes) -> RegistryRecord:
    try:
        raw = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        # the whole file
        return _empty_record(REG_UNREADABLE, "cannot parse %s: %s" % (name, exc))

    return parse_registry_record(raw, path_pid=_pid_from_filename(name))


_FILES = RegistryFileCache()


def _keepable(record: RegistryRecord) -> bool:
    return record.verdict != REG_UNREADABLE


def read_registry_index(
    directory: Optional[str] = None,
    *,
    limit: int = DEFAULT_SCAN_LIMIT,
) -> Mapping[str, RegistryRecord]:
    """Scan the registry directory and key every record by tmux session name.

    Description: one bounded scandir plus one small read per file, and no
        raise on any path.

        DECIDED HERE: a record whose pid is measurably gone is
        :data:`REG_STALE`, the one refusal settleable without knowing
        which session is being asked about. A pid we could not measure
        stays :data:`REG_OK` - unmeasured is not dead.

        DECIDED HERE: two records that are both live and name one tmux
        session collapse to a single :data:`REG_UNREADABLE` entry naming
        every pid involved. The resolver's rung 1 refuses on it and
        raises nothing.

        NOT DECIDED HERE: age. An old ``statusUpdatedAt`` is recorded as
        :data:`REG_OK` and left to the caller, because claude writes this
        file on change and an old timestamp is a true statement about a
        session that has not moved.

        NOT DECIDED HERE: whose session it is. A record belonging to
        somebody else's tmux server is keyed under whatever name it
        carries and simply never matches a lookup. A record with no
        parseable tmux target has no key and is dropped: it cannot be
        about a session this app owns.

        Files we could not parse are keyed under
        :data:`UNREADABLE_KEY_PREFIX` plus their filename so an iterating
        caller sees them. A :data:`REG_SHAPE_UNRECOGNIZED` file is keyed
        under the tmux session it names when that key still reads, so the
        lookup for that session answers the named state, and under the
        prefix otherwise. Those keys contain a colon, which tmux forbids
        in a session name, so they can never collide with a real one.
    Inputs:
        directory: the registry directory. Defaults to
            :func:`default_registry_directory` PLUS each managed account
            profile's ``sessions`` (``profile_roots.claude_registry_roots``).
        limit: how many ``*.json`` files to open, sorted by filename so
            the bound is deterministic rather than filesystem-ordered.
    Output:
        Mapping[str, RegistryRecord] - possibly empty. A missing,
        unreadable or not-a-directory path answers an EMPTY MAPPING and
        raises nothing; every lookup against it then answers
        :data:`REG_ABSENT`, which is already a refusal the resolver
        cannot turn into "done".
    Example:
        >>> dict(read_registry_index("/nonexistent/registry/path"))
        {}
    """
    bases = (
        [directory]
        if directory is not None
        else [str(root) for root in claude_registry_roots()]
    )
    entries: List[Tuple[str, str]] = []
    for base in bases:
        try:
            entries.extend(
                (entry.name, os.path.join(base, entry.name))
                for entry in os.scandir(base)
                if entry.name.endswith(".json") and entry.is_file()
            )
        except OSError:
            # not a directory
            continue
    entries.sort()
    _FILES.retain_only(path for _, path in entries[:limit])
    loaded = ((name, _FILES.load(path, name, _load_registry_file, _keepable))
              for name, path in entries[:limit])
    return index_registry_records(loaded, pid_is_running)


def index_registry_records(
    loaded: Iterable[Tuple[str, RegistryRecord]],
    is_running: Callable[[Optional[int]], Optional[bool]],
) -> Dict[str, RegistryRecord]:
    index: Dict[str, RegistryRecord] = {}
    live_pids: Dict[str, List[Optional[int]]] = {}

    for name, record in loaded:
        if record.verdict == REG_UNREADABLE or (
            record.verdict == REG_SHAPE_UNRECOGNIZED and record.tmux_name is None
        ):
            index[UNREADABLE_KEY_PREFIX + name] = record
            continue

        pid = record.pid if record.verdict == REG_OK else _pid_from_filename(name)
        if is_running(pid) is False:
            record = _empty_record(
                REG_STALE,
                "pid %s in %s is not running" % (pid, name),
                tmux_name=record.tmux_name,
            )

        key = record.tmux_name
        if key is None:
            continue

        if record.verdict == REG_OK:
            seen = live_pids.setdefault(key, [])
            seen.append(record.pid)
            if len(seen) > 1:
                index[key] = _empty_record(
                    REG_UNREADABLE,
                    "two or more live registry records name tmux session %s: pids %s"
                    % (key, ", ".join(str(pid) for pid in seen)),
                    tmux_name=key,
                )
                continue

        existing = index.get(key)
        if existing is None or (record.verdict == REG_OK and existing.verdict != REG_OK):
            index[key] = record

    return index


def _started_before(started_at: datetime, floor: datetime) -> bool:
    try:
        return started_at < floor
    except TypeError:
        return False


def registry_for_session(
    *,
    tmux_name: Optional[str],
    index: Optional[Mapping[str, RegistryRecord]] = None,
    directory: Optional[str] = None,
    session_started_epoch: Optional[int] = None,
    claude_session_uuid: Optional[str] = None,
    process_floor_at: Optional[datetime] = None,
) -> RegistryRecord:
    if not tmux_name:
        return _empty_record(REG_ABSENT, "no tmux session name to look up")

    table = index if index is not None else read_registry_index(directory)
    record = table.get(tmux_name)
    if record is None:
        return _empty_record(
            REG_ABSENT,
            "no registry record names tmux session %s" % tmux_name,
            tmux_name=tmux_name,
        )

    if record.verdict != REG_OK:
        return record

    if process_floor_at is not None and record.started_at is not None:
        if _started_before(record.started_at, process_floor_at):
            return _empty_record(
                REG_STALE,
                "registry record for %s started %s, before this pane's process "
                "was replaced (%s), so it belongs to the process that was replaced"
                % (tmux_name, record.started_at.isoformat(), process_floor_at.isoformat()),
                tmux_name=tmux_name,
            )

    if session_started_epoch is not None and record.started_at is not None:
        floor = _epoch_millis_to_datetime(int(session_started_epoch) * 1000)
        if floor is not None and record.started_at < floor:
            return _empty_record(
                REG_STALE,
                "registry record for %s started %s, before the tmux session it "
                "claims (%s), so it belongs to a previous instance"
                % (tmux_name, record.started_at.isoformat(), floor.isoformat()),
                tmux_name=tmux_name,
            )

    if claude_session_uuid and record.session_uuid:
        if claude_session_uuid != record.session_uuid:
            if (process_floor_at is not None and record.started_at is not None
                    and not _started_before(record.started_at, process_floor_at)):
                return replace(record, stale_cause=STALE_CAUSE_CONVERSATION,
                               record_session_uuid=record.session_uuid)
            return _empty_record(
                REG_STALE,
                "registry record for %s names conversation %s, the row holds %s"
                % (tmux_name, record.session_uuid, claude_session_uuid),
                tmux_name=tmux_name,
                stale_cause=STALE_CAUSE_CONVERSATION,
                record_session_uuid=record.session_uuid,
            )

    return record
