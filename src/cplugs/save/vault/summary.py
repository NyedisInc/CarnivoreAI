
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Type, Union

import structlog

from src.cplugs.save.vault import summary_disk

logger = structlog.get_logger()

from src.cplugs.save.vault import constants as K

from src.cplugs.save.vault import constants as K

if TYPE_CHECKING:  # pragma: no cover
    from src.cplugs.save.vault.manifest import Manifest

FileKey = Tuple[int, int, int]

_COMPACT_SLACK = 1024


def file_key(path: Path) -> FileKey:
    st = os.stat(path)
    return (st.st_ino, st.st_mtime_ns, st.st_size)


@dataclass(frozen=True)
class PointSummary:

    point_id: str
    reason: str
    created_epoch: float
    conversation_id: Optional[str]
    probe: Tuple[str, ...]
    mask: int


def probe_paths(manifest: "Manifest") -> Tuple[str, ...]:
    mains = [f for f in manifest.files if f.role in K.MAIN_ROLES]
    return tuple(sys.intern(f.source_path) for f in (mains or manifest.files))


def probe_of(point: Union["Manifest", PointSummary]) -> Tuple[str, ...]:
    return point.probe if isinstance(point, PointSummary) else probe_paths(point)


@dataclass
class _UnitTable:

    ids: List[str] = field(default_factory=list)
    index: Dict[str, int] = field(default_factory=dict)
    points: Dict[str, Tuple[FileKey, Union[PointSummary, str]]] = field(default_factory=dict)

    def encode(self, hashes: Iterable[str]) -> int:
        rows: List[int] = []
        for sha in hashes:
            row = self.index.get(sha)
            if row is None:
                row = self.index[sha] = len(self.ids)
                self.ids.append(sys.intern(sha))
            rows.append(row)
        bits = bytearray(len(self.ids) // 8 + 1)
        for row in rows:
            bits[row >> 3] |= 1 << (row & 7)
        return int.from_bytes(bits, "little")

    def decode(self, mask: int) -> Set[str]:
        ids, found, at = self.ids, set(), -1
        digits = bin(mask)[:1:-1]
        while (at := digits.find("1", at + 1)) >= 0:
            found.add(ids[at])
        return found

    def compact(self) -> None:
        live = [(pid, key, s) for pid, (key, s) in self.points.items() if isinstance(s, PointSummary)]
        union = 0
        for _pid, _key, s in live:
            union |= s.mask
        if len(self.ids) <= 2 * union.bit_count() + _COMPACT_SLACK:
            return
        old = _UnitTable(self.ids, self.index)
        self.ids, self.index = [], {}
        for pid, key, s in live:
            remapped = PointSummary(s.point_id, s.reason, s.created_epoch, s.conversation_id, s.probe,
                                    self.encode(old.decode(s.mask)))
            self.points[pid] = (key, remapped)


def _rows_of_table(table: _UnitTable) -> Dict[str, Any]:
    points: Dict[str, List[Any]] = {}
    for pid, (key, seen) in table.points.items():
        if isinstance(seen, str):
            points[pid] = [*key, seen]
        else:
            mask = seen.mask.to_bytes((seen.mask.bit_length() + 7) // 8, "little").hex()
            points[pid] = [*key, None, seen.point_id, seen.reason, seen.created_epoch, seen.conversation_id,
                           list(seen.probe), mask]
    return {"ids": table.ids, "points": points}


def _table_from_rows(data: Dict[str, Any]) -> _UnitTable:
    ids = [sys.intern(str(sha)) for sha in data["ids"]]
    table = _UnitTable(ids=ids, index={sha: row for row, sha in enumerate(ids)})
    for pid, row in data["points"].items():
        key: FileKey = (int(row[0]), int(row[1]), int(row[2]))
        if row[3] is not None:
            table.points[str(pid)] = (key, str(row[3]))
            continue
        mask = int.from_bytes(bytes.fromhex(row[9]), "little")
        if mask.bit_length() > len(ids):
            raise ValueError(f"mask of {pid} names chunks past the table")
        table.points[str(pid)] = (key, PointSummary(
            str(row[4]), str(row[5]), float(row[6]), None if row[7] is None else str(row[7]),
            tuple(sys.intern(str(p)) for p in row[8]), mask))
    return table


class SummaryCache:

    def __init__(self, failure: Type[Exception], path: Optional[Path] = None) -> None:
        self._failure = failure
        self._path = path
        self._lock = threading.Lock()
        self._units: Dict[str, _UnitTable] = {}
        self._loaded = path is None
        self._dirty = False
        self.parses = 0

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None:
            return
        try:
            stored = summary_disk.load(self._path.read_bytes())
            self._units = {unit: _table_from_rows(data) for unit, data in stored.items()}
        except FileNotFoundError:
            return
        except (OSError, summary_disk.SummaryStoreError, KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.warning("vault_summaries_discarded", path=str(self._path), error=str(exc),
                           note="the next pass re-reads the manifests and rebuilds it")
            self._units = {}
            self._path.unlink(missing_ok=True)

    def save(self) -> bool:
        with self._lock:
            if self._path is None or not self._dirty:
                return False
            rows = {unit: _rows_of_table(table) for unit, table in self._units.items()}
            self._dirty = False
        try:
            summary_disk.write_atomic(self._path, summary_disk.dump(rows))
        except OSError as exc:
            logger.warning("vault_summaries_unwritten", path=str(self._path), error=str(exc))
            with self._lock:
                self._dirty = True
            return False
        return True

    def get(self, path: Path, unit: str, point_id: str, load: Callable[[], "Manifest"]) -> PointSummary:
        try:
            key: Optional[FileKey] = file_key(path)
        except OSError:
            key = None
        with self._lock:
            self._ensure_loaded()
            table = self._units.setdefault(unit, _UnitTable())
            seen = table.points.get(point_id)
            if key is None:
                self._dirty |= table.points.pop(point_id, None) is not None
            elif seen is not None and seen[0] == key:
                if isinstance(seen[1], str):
                    raise self._failure(seen[1])
                return seen[1]
        self.parses += 1
        try:
            manifest = load()
        except self._failure as exc:
            if key is not None:
                with self._lock:
                    self._units.setdefault(unit, _UnitTable()).points[point_id] = (key, str(exc))
                    self._dirty = True
            raise
        with self._lock:
            table = self._units.setdefault(unit, _UnitTable())
            found = PointSummary(manifest.point_id, manifest.reason, manifest.created_epoch, manifest.conversation_id,
                                 probe_paths(manifest), table.encode(manifest.chunk_hashes()))
            if key is not None:
                table.points[point_id] = (key, found)
                self._dirty = True
        return found

    def chunks(self, unit: str, mask: int) -> Set[str]:
        with self._lock:
            self._ensure_loaded()
            table = self._units.get(unit)
            return table.decode(mask) if table is not None and mask else set()

    def prune(self, unit: str, point_ids: Iterable[str]) -> None:
        live = set(point_ids)
        with self._lock:
            self._ensure_loaded()
            table = self._units.get(unit)
            if table is None:
                return
            gone = [p for p in table.points if p not in live]
            for pid in gone:
                del table.points[pid]
            before = len(table.ids)
            table.compact()
            self._dirty |= bool(gone) or len(table.ids) != before

    def retain(self, units: Iterable[str]) -> None:
        keep = set(units)
        with self._lock:
            self._ensure_loaded()
            for unit in [u for u in self._units if u not in keep]:
                del self._units[unit]
                self._dirty = True

    def footprint(self) -> Dict[str, int]:
        with self._lock:
            tables = list(self._units.values())
            summaries = [s for t in tables for _k, s in t.points.values() if isinstance(s, PointSummary)]
            return {"units": len(tables), "points": sum(len(t.points) for t in tables),
                    "chunk_rows": sum(len(t.ids) for t in tables),
                    "mask_bytes": sum((s.mask.bit_length() + 7) // 8 for s in summaries)}
