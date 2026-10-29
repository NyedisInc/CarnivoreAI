
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from src.core.attention.registry_file_cache import RegistryFileCache
from src.core.attention.registry_record import (
    REG_ABSENT, REG_OK, REG_SHAPE_UNRECOGNIZED, REG_STALE, REG_UNREADABLE,
    STALE_CAUSE_CONVERSATION, RegistryRecord, _empty_record,
    _epoch_millis_to_datetime, _pid_from_filename, load_registry_blob,
)
from src.core.claude_config.profile_roots import claude_registry_roots
from src.core.stat_gate.dir_names import entry_names

REGISTRY_DIRNAME: str = os.path.join(".claude", "sessions")

DEFAULT_SCAN_LIMIT: int = 128

MAX_REGISTRY_FILE_BYTES: int = 64 * 1024

UNREADABLE_KEY_PREFIX: str = "?unreadable:"


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
        return None
    return True


def default_registry_directory() -> str:
    return os.path.join(os.path.expanduser("~"), REGISTRY_DIRNAME)


def _load_registry_file(path: str, name: str) -> RegistryRecord:
    try:
        with open(path, "rb") as handle:
            blob = handle.read(MAX_REGISTRY_FILE_BYTES)
    except OSError as exc:
        return _empty_record(REG_UNREADABLE, "cannot read %s: %s" % (name, exc))
    return load_registry_blob(name, blob)


_FILES = RegistryFileCache()


def _keepable(record: RegistryRecord) -> bool:
    return record.verdict != REG_UNREADABLE


def read_registry_index(
    directory: Optional[str] = None,
    *,
    limit: int = DEFAULT_SCAN_LIMIT,
) -> Mapping[str, RegistryRecord]:
    bases = (
        [directory]
        if directory is not None
        else [str(root) for root in claude_registry_roots()]
    )
    entries: List[Tuple[str, str]] = []
    for base in bases:
        try:
            entries.extend(
                (name, os.path.join(base, name))
                for name in entry_names(base, files_only=True)
                if name.endswith(".json")
            )
        except OSError:
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
                    ambiguous_pane=True,
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
