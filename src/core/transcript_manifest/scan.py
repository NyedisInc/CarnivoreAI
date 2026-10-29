"""One scan: compare what is on disk with the manifest rows and decide each file's outcome.

STAT ONLY FOR AN UNCHANGED FILE. A file whose size and mtime match its row, and whose row already
knows its last serial, is never opened. Anything else reads only its tail (``tail.read_last_line``):

- added: a path with no row (or a row a previous scan marked gone, which is a new file again);
- unchanged: same size and mtime as the row;
- grown: larger, and the row's last serial is still at the row's last offset (that one line is read);
- rewritten: the row's last serial is no longer where it was (a shrink, a rewrite, a replace);
- removed: a present row whose path the walk did not list AND that ``lstat`` confirms is gone. A root
  the walk could not read proves nothing, so rows under it are never marked removed;
- dataless: an iCloud placeholder (``SF_DATALESS`` in ``st_flags``, checked with ``lstat`` BEFORE any
  read). It is counted and its row keeps what it had; a new one gets a row with no serial;
- unreadable: stat or the tail read failed with anything other than "gone".

A same-size, new-mtime file whose serial is still in place is ``unchanged`` (touched, not changed).

PURE OF SQL: :func:`scan` takes the prior rows and the observed files and returns the rows to write,
so a dry run and a live run make exactly the same decisions (``store.persist`` writes them).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

import structlog

from src.core.transcript_manifest import constants as K
from src.core.transcript_manifest.tail import LastLine, read_last_line, serial_at

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Observed:

    path: str
    family: str
    root: str
    source_path: str
    conversation_id: Optional[str]
    kind: str


@dataclass(frozen=True)
class Row:

    path: str
    family: str
    root: str
    source_path: str
    conversation_id: Optional[str]
    kind: str
    size: int
    mtime_ns: int
    last_line_uuid: Optional[str]
    last_line_offset: Optional[int]
    complete_bytes: Optional[int]
    prev_size: Optional[int]
    prev_last_line_uuid: Optional[str]
    prev_last_line_offset: Optional[int]
    prev_complete_bytes: Optional[int]
    dataless: int
    status: str
    first_seen: str
    last_seen: str
    changed_at: str
    gone_at: Optional[str]
    id: Optional[int] = None


@dataclass
class ScanResult:

    counts: Dict[str, int] = field(default_factory=lambda: {o: 0 for o in K.OUTCOMES})
    changed: List[Row] = field(default_factory=list)
    present: List[Row] = field(default_factory=list)
    removed: List[Row] = field(default_factory=list)
    complete_roots: Set[str] = field(default_factory=set)
    unreadable_roots: Set[str] = field(default_factory=set)
    # could not
    discovery_unreadable: int = 0
    # could not be read
    unreadable_sample: List[Dict[str, str]] = field(default_factory=list)

    def summary(self) -> Dict[str, object]:
        return {**self.counts, "files": len(self.present), "discovery_unreadable": self.discovery_unreadable,
                "unreadable_roots": sorted(self.unreadable_roots)}


Lstat = Callable[[str], os.stat_result]
_lstat: Lstat = os.lstat


def is_dataless(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_flags", 0) & K.SF_DATALESS)


def _new_row(obs: Observed, st: os.stat_result, tail: LastLine, now: str, *, dataless: bool) -> Row:
    return Row(obs.path, obs.family, obs.root, obs.source_path, obs.conversation_id, obs.kind,
               st.st_size, st.st_mtime_ns, tail.serial, tail.offset, tail.end, None, None, None, None,
               int(dataless), K.STATUS_PRESENT, now, now, now, None)


def _changed_row(old: Row, obs: Observed, st: os.stat_result, tail: LastLine, status: str, now: str) -> Row:
    return replace(old, family=obs.family, root=obs.root, source_path=obs.source_path,
                   conversation_id=obs.conversation_id, kind=obs.kind, size=st.st_size, mtime_ns=st.st_mtime_ns,
                   last_line_uuid=tail.serial, last_line_offset=tail.offset, complete_bytes=tail.end,
                   prev_size=old.size, prev_last_line_uuid=old.last_line_uuid,
                   prev_last_line_offset=old.last_line_offset, prev_complete_bytes=old.complete_bytes,
                   dataless=0, status=status,
                   last_seen=now, changed_at=now, gone_at=None)


def _old_serial_in_place(path: str, old: Row) -> bool:
    if old.last_line_uuid is None or old.last_line_offset is None:
        return False
    return serial_at(Path(path), old.last_line_offset) == old.last_line_uuid


def _classify(obs: Observed, old: Optional[Row], st: os.stat_result, now: str) -> tuple:
    if old is None or old.gone_at is not None:
        tail = read_last_line(Path(obs.path), st.st_size)
        row = _new_row(obs, st, tail, now, dataless=False)
        if old is not None:
            row = replace(row, id=old.id, first_seen=old.first_seen)
        return K.OUT_ADDED, row
    known = old.last_line_offset is not None or old.size == 0
    if st.st_size == old.size and st.st_mtime_ns == old.mtime_ns and known and not old.dataless:
        return K.OUT_UNCHANGED, None
    in_place = known and _old_serial_in_place(obs.path, old)
    tail = read_last_line(Path(obs.path), st.st_size)
    if st.st_size > old.size and (in_place or old.size == 0):
        return K.OUT_GROWN, _changed_row(old, obs, st, tail, K.STATUS_GROWN, now)
    if st.st_size == old.size and (in_place or not known or old.size == 0):
        return K.OUT_UNCHANGED, replace(old, mtime_ns=st.st_mtime_ns, last_line_uuid=tail.serial,
                                        last_line_offset=tail.offset, complete_bytes=tail.end,
                                        dataless=0, last_seen=now)
    return K.OUT_REWRITTEN, _changed_row(old, obs, st, tail, K.STATUS_REWRITTEN, now)


def _note_unreadable(result: ScanResult, path: str, exc: OSError) -> None:
    result.counts[K.OUT_UNREADABLE] += 1
    if len(result.unreadable_sample) < 20:
        result.unreadable_sample.append({"path": path, "reason": f"{type(exc).__name__}: {exc}"})


def _keep_unread(result: ScanResult, obs: Observed, old: Optional[Row], st: os.stat_result, now: str,
                 *, dataless: bool) -> None:
    if old is not None and old.gone_at is None:
        result.present.append(old)
        return
    row = _new_row(obs, st, LastLine(None, None, None), now, dataless=dataless)
    row = replace(row, id=old.id, first_seen=old.first_seen) if old is not None else row
    result.changed.append(row)
    result.present.append(row)


def _one(result: ScanResult, obs: Observed, old: Optional[Row], now: str, lstat: Lstat) -> None:
    try:
        st = lstat(obs.path)
    except FileNotFoundError:
        return
    except OSError as exc:
        _note_unreadable(result, obs.path, exc)
        if old is not None and old.gone_at is None:
            result.present.append(old)
        return
    if is_dataless(st):
        result.counts[K.OUT_DATALESS] += 1
        _keep_unread(result, obs, old, st, now, dataless=True)
        return
    try:
        outcome, row = _classify(obs, old, st, now)
    except FileNotFoundError:
        return
    except OSError as exc:
        _note_unreadable(result, obs.path, exc)
        _keep_unread(result, obs, old, st, now, dataless=False)
        return
    result.counts[outcome] += 1
    if row is not None:
        result.changed.append(row)
    result.present.append(row if row is not None else old)


def scan(prior: Dict[str, Row], observed: Iterable[Observed], *, complete_roots: Sequence[str],
         unreadable_roots: Sequence[str] = (), now: str, lstat: Optional[Lstat] = None) -> ScanResult:
    lstat = lstat or _lstat
    result = ScanResult(complete_roots=set(complete_roots), unreadable_roots=set(unreadable_roots))
    listed: Set[str] = set()
    for obs in observed:
        if obs.path in listed:
            continue
        listed.add(obs.path)
        _one(result, obs, prior.get(obs.path), now, lstat)
    for path, old in prior.items():
        if old.gone_at is not None or path in listed or old.root not in result.complete_roots:
            continue
        try:
            lstat(path)
            continue
        except FileNotFoundError:
            pass
        except OSError:
            continue
        gone = replace(old, status=K.STATUS_GONE, gone_at=now, changed_at=now)
        result.counts[K.OUT_REMOVED] += 1
        result.changed.append(gone)
        result.removed.append(gone)
    return result
