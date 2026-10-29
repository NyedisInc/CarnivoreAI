
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import os
import time
import structlog

from src.core.blobcodec.place import (
    PlaceConflict, PlaceMismatch, apply_metadata, file_matches, sha256_file, stage_verified, write_verified,
)
from src.core.crate_format.constants import HOME_CLAUDE, HOME_CODEX
from src.core.crate_format.errors import CrateError
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import files_place, undo
from src.core.crate_import.analysis import Analysis
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.hooks import PHASE_FILES, ApplyHooks
from src.core.crate_import.model import CLASS_GROW, CLASS_WRITE, ImportFailed

logger = structlog.get_logger()

E_UNSAFE = "unsafe_destination"
E_FILE_CHANGED = "destination_changed"
E_CRATE_BYTES = "crate_bytes_wrong"
E_IO = "io_failed"


@dataclass
class PlacedFiles:

    written: List[str] = field(default_factory=list)
    same: List[str] = field(default_factory=list)
    bytes: int = 0
    log: List[Dict[str, Any]] = field(default_factory=list)
    project_written: int = 0
    project_links: int = 0
    project_links_skipped: List[str] = field(default_factory=list)
    root_side: Optional[Path] = None
    restamp_ns: int = 0
    cleanup: Dict[str, Any] = field(default_factory=dict)
    backups: Dict[str, Any] = field(default_factory=dict)


def _homes(env: ImportEnv) -> Dict[str, Path]:
    return {HOME_CLAUDE: Path(env.claude_homes[0]), HOME_CODEX: Path(env.codex_home)}


def undo_roots(env: ImportEnv) -> List[Path]:
    return [*[Path(h) for h in env.claude_homes], Path(env.codex_home)]


def stamp_of(p: files_place.Placement, placed: PlacedFiles) -> Optional[int]:
    return (placed.restamp_ns or p.record.mtime_ns) if p.record.role in files_place.CONVERSATION_ROLES else p.record.mtime_ns


def record_undo(hooks: ApplyHooks, placed: PlacedFiles, entry: Dict[str, Any]) -> None:
    if placed.root_side is not None and entry.get("side") == str(placed.root_side):
        entry["project_root"] = True
    hooks.undo(entry)
    placed.log.append(entry)


def make_parents(dest: Path, home: Path, hooks: ApplyHooks, placed: PlacedFiles, side: Optional[Path] = None) -> None:
    missing: List[Path] = []
    folder = dest.parent
    while folder != home and not folder.exists() and home in folder.parents:
        missing.append(folder)
        folder = folder.parent
    for folder in reversed(missing):
        record_undo(hooks, placed, undo.dir_entry(folder, side))
        folder.mkdir(mode=0o755 if side is not None else 0o700, exist_ok=True)


def _old_chunks(path: Path, length: int) -> Iterator[bytes]:
    left = length
    with open(path, "rb") as handle:
        while left > 0:
            block = handle.read(min(1 << 20, left))
            if not block:
                return
            left -= len(block)
            yield block


def _backup(p: files_place.Placement, home: Path, old_length: int, old_sha: str, import_id: str, env: ImportEnv) -> Path:
    """Copy the local file's bytes to the receipts folder (never replacing a backup already there). Output: the backup path.

    Raises: ImportFailed (the file is no longer what was proved a prefix; the backup could not be written).
    """
    assert p.dest is not None
    backup = env.backup_dir(import_id) / p.record.home / p.dest.relative_to(home)
    backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        write_verified(_old_chunks(p.dest, old_length), backup, length=old_length, sha256=old_sha)
    except PlaceConflict:
        if not file_matches(backup, old_sha, old_length):
            raise ImportFailed(E_FILE_CHANGED, f"{backup.name}: a different backup is already there", rolled_back=False) from None
    except PlaceMismatch as exc:
        raise ImportFailed(E_FILE_CHANGED, f"{p.dest.name}: changed while it was backed up", rolled_back=False) from exc
    except OSError as exc:
        raise ImportFailed(E_IO, f"{backup}: {type(exc).__name__}", rolled_back=False) from exc
    return backup


def _grow(p: files_place.Placement, reader: CrateReader, home: Path, env: ImportEnv, hooks: ApplyHooks, placed: PlacedFiles,
          import_id: str) -> None:
    assert p.dest is not None
    old_length = files_place.grow_size(p.dest, p.record, reader)
    if old_length is None:
        raise ImportFailed(E_FILE_CHANGED, f"{p.dest.name}: is no longer a shorter copy of the crate's file", rolled_back=False)
    try:
        old_sha = sha256_file(p.dest)
    except OSError as exc:
        raise ImportFailed(E_IO, f"{p.dest}: {type(exc).__name__}", rolled_back=False) from exc
    backup = _backup(p, home, old_length, old_sha, import_id, env)
    record_undo(hooks, placed, undo.grow_entry(p.dest, backup, old_sha, old_length, p.record.content_sha256, p.record.length))
    try:
        temp = stage_verified(reader.file_chunks(p.record), p.dest, length=p.record.length, sha256=p.record.content_sha256)
    except (PlaceMismatch, CrateError) as exc:
        raise ImportFailed(E_CRATE_BYTES, f"{p.dest.name}: {type(exc).__name__}", rolled_back=False) from exc
    except OSError as exc:
        raise ImportFailed(E_IO, f"{p.dest}: {type(exc).__name__}", rolled_back=False) from exc
    try:
        if files_place.grow_size(p.dest, p.record, reader) != old_length or not file_matches(p.dest, old_sha, old_length):
            raise ImportFailed(E_FILE_CHANGED, f"{p.dest.name}: changed while the longer copy was staged", rolled_back=False)
        os.replace(temp, p.dest)
        apply_metadata(p.dest, p.record.mode, stamp_of(p, placed))
    except OSError as exc:
        raise ImportFailed(E_IO, f"{p.dest}: {type(exc).__name__}", rolled_back=False) from exc
    finally:
        temp.unlink(missing_ok=True)
    placed.written.append(str(p.dest))
    placed.bytes += p.record.length - old_length
    hooks.add(p.record.length - old_length, 1)


def place_files(reader: CrateReader, a: Analysis, env: ImportEnv, hooks: ApplyHooks, import_id: str = "") -> PlacedFiles:
    writing = {c["id"] for c in a.conversations if c["class"] in (CLASS_WRITE, CLASS_GROW)}
    todo = [p for p in a.placements if p.action == files_place.ACT_PLACE and p.dest is not None
            and (p.record.conversation_id is None or p.record.conversation_id in writing)]
    homes, placed = _homes(env), PlacedFiles()
    placed.restamp_ns = time.time_ns()
    writes = (files_place.CLASS_ABSENT, files_place.CLASS_GROW)
    side = a.side
    hooks.phase(PHASE_FILES, total=sum(p.record.length for p in todo if p.cls in writes) + (side.bytes if side else 0),
                files=sum(1 for p in todo if p.cls in writes) + (len(side.files) if side else 0))
    for p in todo:
        hooks.check()
        if p.cls == files_place.CLASS_SAME:
            placed.same.append(str(p.dest))
            continue
        if p.cls not in (files_place.CLASS_ABSENT, files_place.CLASS_GROW):
            continue
        home = p.home or homes[p.record.home]
        problem = files_place.contained(p.dest, home)
        if problem is not None:
            raise ImportFailed(E_UNSAFE, f"{p.dest}: {problem}", rolled_back=False)
        if p.cls == files_place.CLASS_GROW:
            _grow(p, reader, home, env, hooks, placed, import_id)
            continue
        try:
            make_parents(p.dest, home, hooks, placed)
            record_undo(hooks, placed, undo.file_entry(p.dest, p.record.content_sha256, p.record.length))
            written = write_verified(reader.file_chunks(p.record), p.dest, length=p.record.length, sha256=p.record.content_sha256,
                                     mode=p.record.mode, mtime_ns=stamp_of(p, placed))
        except PlaceConflict as exc:
            raise ImportFailed(E_FILE_CHANGED, f"{exc}: a file appeared at the destination after the preview", rolled_back=False) from exc
        except (PlaceMismatch, CrateError) as exc:
            raise ImportFailed(E_CRATE_BYTES, f"{p.dest.name}: {type(exc).__name__}", rolled_back=False) from exc
        except OSError as exc:
            raise ImportFailed(E_IO, f"{p.dest}: {type(exc).__name__}", rolled_back=False) from exc
        placed.written.append(str(p.dest))
        placed.bytes += written
        hooks.add(written, 1)
    return placed
