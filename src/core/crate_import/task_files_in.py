
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.blobcodec.place import PlaceConflict, PlaceMismatch, write_verified
from src.core.crate_format.constants import HOME_STATE
from src.core.crate_format.errors import CrateError
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import files_place, undo
from src.core.crate_import.idmap import IdMap
from src.core.crate_import.model import W_TASK_FILE_FAILED, W_TASK_FILE_KEPT, Collector
from src.core.inventory.model import MAIN_STORE

logger = structlog.get_logger()

ROLE = "task_file"
ITEMS = f"{MAIN_STORE}.work_items"
_REL = re.compile(r"^cplugs/huddle/files/(\d+)/([^/].*)$")
FILES_DIR: Tuple[str, ...] = ("cplugs", "huddle", "files")
SCOPE_TASK_FILES = "task_files"


@dataclass
class TaskFilesOutcome:

    written: List[str] = field(default_factory=list)
    same: List[str] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    no_item: int = 0
    failed: List[str] = field(default_factory=list)

    def as_json(self) -> Dict[str, object]:
        return {"written": len(self.written), "same": len(self.same), "no_item": self.no_item, "kept": list(self.kept),
                "failed": list(self.failed)}


def carried(records: List[FileRecord]) -> List[Tuple[FileRecord, int, str]]:
    out: List[Tuple[FileRecord, int, str]] = []
    for record in records:
        found = _REL.match(record.rel) if record.role == ROLE and record.home == HOME_STATE else None
        if found is None or any(part in ("", ".", "..") for part in found.group(2).split("/")):
            continue
        out.append((record, int(found.group(1)), found.group(2)))
    return out


def destination(state: Path, new_item: int, rest: str) -> Path:
    return Path(state).joinpath(*FILES_DIR, str(int(new_item)), *rest.split("/"))


def place_task_files(reader: CrateReader, state: Path, idmap: IdMap, col: Optional[Collector] = None,
                     log: Optional[Callable[[Dict[str, Any]], None]] = None) -> TaskFilesOutcome:
    out = TaskFilesOutcome()
    for record, old_item, rest in carried(reader.files()):
        new_item = idmap.get(ITEMS, old_item)
        if new_item is None:
            out.no_item += 1
            continue
        dest = destination(state, new_item, rest)
        problem = files_place.contained(dest, Path(state))
        if problem is not None:
            out.failed.append(f"{dest}: {problem}")
            continue
        cls, _why = files_place.classify(dest, record, reader)
        if cls == files_place.CLASS_SAME:
            out.same.append(str(dest))
            continue
        if cls != files_place.CLASS_ABSENT:
            out.kept.append(str(dest))
            if col is not None:
                col.warn(W_TASK_FILE_KEPT, str(dest))
            continue
        try:
            if log is not None:
                for entry in undo.creation_entries(dest, Path(state).joinpath(*FILES_DIR), record.content_sha256, record.length, {SCOPE_TASK_FILES: True}):
                    log(entry)
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_verified(reader.file_chunks(record), dest, length=record.length, sha256=record.content_sha256, mode=record.mode,
                           mtime_ns=record.mtime_ns)
        except PlaceConflict:
            out.kept.append(str(dest))
        except (PlaceMismatch, CrateError, OSError) as exc:
            logger.warning("crate_import_task_file_failed", dest=str(dest), error_type=type(exc).__name__)
            out.failed.append(f"{dest}: {type(exc).__name__}")
            if col is not None:
                col.warn(W_TASK_FILE_FAILED, str(dest))
        else:
            out.written.append(str(dest))
    return out
