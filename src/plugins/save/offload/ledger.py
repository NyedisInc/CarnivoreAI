
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, FrozenSet, Iterable, List, Optional, Tuple

import structlog

from src.plugins.save.engine import layout
from src.plugins.save.offload import constants as C, push
from src.plugins.save.vault import constants as K
from src.plugins.sdk import offloaded_marker

logger = structlog.get_logger()

_LOCK = threading.RLock()


OPERATION = threading.Lock()


class LedgerUnreadable(RuntimeError):
    pass


class UnknownField(ValueError):
    pass


class MarkerNotWritten(OSError):
    pass


@dataclass
class Entry:

    conversation_id: str
    unit: str
    family: str
    encoded_folder: Optional[str]
    point_id: str
    manifest_sha256: str
    files: int
    bytes: int
    group: List[str] = field(default_factory=list)
    state: str = C.STATE_OFFLOADING
    offloaded_at: float = 0.0
    restored_at: Optional[float] = None
    holding_dir: str = ""
    purge_after: Optional[float] = None
    purged_at: Optional[float] = None
    error: str = ""
    error_code: str = ""
    error_path: str = ""


_REASON_FIELDS: Tuple[str, ...] = ("error_code", "error_path")


def _entry_from(raw: Any) -> Entry:
    names = {f.name for f in fields(Entry)}
    if not isinstance(raw, dict) or not {"conversation_id", "unit", "point_id", "state"} <= set(raw) or raw["state"] not in C.STATES:
        raise LedgerUnreadable("a ledger row is malformed")
    try:
        return Entry(**{k: v for k, v in raw.items() if k in names})
    except TypeError as exc:
        raise LedgerUnreadable(f"a ledger row is malformed: {exc}") from exc


def prev_path(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + C.LEDGER_PREV_SUFFIX)


def _holds_a_file(root: Path) -> bool:
    if not os.path.lexists(root):
        return False

    def fail(exc: OSError) -> None:
        raise exc

    return any(files for _folder, _subfolders, files in os.walk(root, onerror=fail))


def absence_doubt(path: Path, state_dir: Optional[Path] = None) -> Optional[str]:
    prev = prev_path(path)
    if os.path.lexists(prev):
        return f"{Path(path).name} is missing but its previous copy {prev} is there: the ledger was lost, not emptied"
    if state_dir is None:
        return None
    holding = Path(state_dir) / C.HOLDING_DIRNAME
    try:
        if _holds_a_file(holding):
            return f"{Path(path).name} is missing while files are still held in {holding} (its previous copy would be {prev})"
    except OSError as exc:
        return f"{Path(path).name} is missing and the holding folder {holding} cannot be read ({exc.strerror or exc})"
    marker = offloaded_marker.read(Path(state_dir), quiet=True)
    if marker.unreadable or marker.rows:
        listed = "cannot be read" if marker.unreadable else f"lists {len(marker.rows)} conversation(s)"
        return f"{Path(path).name} is missing while the offloaded marker in {state_dir} {listed} (its previous copy would be {prev})"
    return None


def read_file(path: Path, state_dir: Optional[Path] = None) -> Dict[str, Entry]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        doubt = absence_doubt(path, state_dir)
        if doubt is not None:
            raise LedgerUnreadable(doubt) from None
        return {}
    except (OSError, ValueError) as exc:
        raise LedgerUnreadable(f"{Path(path).name} cannot be read: {exc}") from exc
    rows = data.get("conversations") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        raise LedgerUnreadable(f"{Path(path).name} is malformed")
    return {cid: _entry_from(row) for cid, row in rows.items()}


class Ledger:

    def __init__(self, vault_root: Path, state_dir: Path) -> None:
        self.path = Path(vault_root) / K.OFFLOAD_FILE
        self.state_dir = Path(state_dir)

    def locked(self) -> ContextManager[Any]:
        return _LOCK

    @property
    def prev(self) -> Path:
        return prev_path(self.path)

    def read(self) -> Dict[str, Entry]:
        return read_file(self.path, self.state_dir)

    def _keep_previous(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        layout.atomic_write_text(self.prev, text)

    def _write(self, entries: Dict[str, Entry], *, dropped: Tuple[str, ...] = (), require_marker: bool = False) -> None:
        self._keep_previous()
        layout.atomic_write_json(self.path, {"version": 1, "conversations": {cid: asdict(e) for cid, e in sorted(entries.items())}})
        push.changed()
        if not self._sync(entries, dropped) and require_marker:
            raise MarkerNotWritten(f"the offloaded marker in {self.state_dir} could not be written")

    def _sync(self, entries: Dict[str, Entry], dropped: Tuple[str, ...] = ()) -> bool:
        rows: Dict[str, Tuple[str, Iterable[str], int]] = {}
        times: Dict[str, float] = {}
        current = offloaded_marker.read(self.state_dir)
        if current.unreadable:
            logger.error("offload_marker_unreadable_rewritten", entries=len(entries))
        for cid, row in current.rows.items():
            if cid not in dropped:
                rows[cid] = (cid, row.sessions, row.bytes)
                times[cid] = row.offloaded_at
        for e in entries.values():
            rows[e.conversation_id] = (e.conversation_id, e.group, e.bytes)
            times[e.conversation_id] = e.offloaded_at
        if offloaded_marker.write(self.state_dir, rows.values(), times):
            return True
        logger.error("offload_marker_not_written", entries=len(entries), note="the ledger is the truth; the core guard may not know until the next change or start")
        return False

    def sync_marker(self, on_disk: Optional[Callable[[str], bool]] = None) -> None:
        with _LOCK:
            entries = read_file(self.path) if self.path.exists() else {}
            stale: Tuple[str, ...] = ()
            if on_disk is not None:
                stale = tuple(cid for cid in offloaded_marker.read(self.state_dir).rows if cid not in entries and on_disk(cid))
                if stale:
                    logger.warning("offload_marker_stale_rows_dropped", conversations=list(stale))
            self._sync(entries, stale)

    def get(self, conversation_id: str) -> Optional[Entry]:
        return self.read().get(conversation_id)

    def put(self, entry: Entry) -> None:
        with _LOCK:
            entries = self.read()
            entries[entry.conversation_id] = entry
            self._write(entries, require_marker=True)

    def remove(self, conversation_id: str) -> None:
        with _LOCK:
            entries = self.read()
            if entries.pop(conversation_id, None) is not None:
                self._write(entries, dropped=(conversation_id,))

    def update(self, conversation_id: str, **changes: Any) -> Optional[Entry]:
        unknown = sorted(set(changes) - {f.name for f in fields(Entry)})
        if unknown:
            raise UnknownField(f"a ledger entry has no field {', '.join(unknown)}")
        if "error" in changes:
            changes = {**{name: "" for name in _REASON_FIELDS}, **changes}
        with _LOCK:
            entries = self.read()
            entry = entries.get(conversation_id)
            if entry is None:
                return None
            for key, value in changes.items():
                setattr(entry, key, value)
            self._write(entries)
            return entry


def intentional_units(vault_root: Path) -> FrozenSet[str]:
    try:
        return frozenset(e.unit for e in read_file(Path(vault_root) / K.OFFLOAD_FILE).values())
    except LedgerUnreadable as exc:
        logger.error("offload_ledger_unreadable_for_gone_watch", error=str(exc)[:200])
        return frozenset()


@dataclass(frozen=True)
class OffloadedUnits:

    units: FrozenSet[str] = frozenset()
    unreadable: bool = False

    def holds(self, unit: str) -> bool:
        return self.unreadable or unit in self.units


_UNITS_CACHE: Dict[str, Tuple[Optional[Tuple[int, int, int]], OffloadedUnits]] = {}
_UNITS_LOCK = threading.Lock()


def _stamp(path: Path) -> Optional[Tuple[int, int, int]]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def offloaded_units(vault_root: Path, *, state_dir: Optional[Path] = None) -> OffloadedUnits:
    path = Path(vault_root) / K.OFFLOAD_FILE
    key = f"{path}|{state_dir or ''}"
    try:
        stamp = _stamp(path)
    except OSError as exc:
        logger.error("offload_ledger_unreadable_for_keepers", error=str(exc)[:200])
        return OffloadedUnits(unreadable=True)
    with _UNITS_LOCK:
        hit = _UNITS_CACHE.get(key)
    if stamp is not None and hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        answer = OffloadedUnits(frozenset(e.unit for e in read_file(path, state_dir).values()))
    except LedgerUnreadable as exc:
        answer = OffloadedUnits(unreadable=True)
        if not (stamp is None and hit is not None and hit[0] is None and hit[1].unreadable):
            logger.error("offload_ledger_unreadable_for_keepers", error=str(exc)[:200])
    with _UNITS_LOCK:
        _UNITS_CACHE[key] = (stamp, answer)
    return answer


def offload_in_flight(vault_root: Path, state_dir: Path) -> bool:
    answer = offloaded_units(vault_root, state_dir=state_dir)
    if answer.unreadable or answer.units:
        return True
    try:
        return _holds_a_file(Path(state_dir) / C.HOLDING_DIRNAME)
    except OSError:
        return True


def protects(vault_root: Path, unit: str, point_id: str) -> bool:
    entry = read_file(Path(vault_root) / K.OFFLOAD_FILE).get(unit)
    return entry is not None and entry.point_id == point_id
