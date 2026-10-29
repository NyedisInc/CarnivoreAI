
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.core.blobcodec.place import PlaceConflict, PlaceMismatch, write_verified
from src.cplugs.sdk import ports, task_folders

logger = structlog.get_logger()

FILES_DIR: Tuple[str, ...] = ("cplugs", "huddle", "files")
REL_PREFIX = "files"
FILE_MODE = 0o600
DIR_MODE = 0o700
NOT_HERE_LINE = "[{name} was not on this computer]"
_FILES_KEYS = ("files",)
_RELATIVE = re.compile(rf"^{REL_PREFIX}/(\d+)/(.+)$")
_BLOCK = 1 << 20

OnCreate = Callable[[Path, str, int], None]
Select = Callable[[Dict[str, Any]], bool]


def configured_roots() -> List[Path]:
    port = ports.get(task_folders.ROOT_PORT)
    root = port.root() if port is not None else None
    return [Path(root)] if root is not None else []


@dataclass
class FileHome:

    state: Path
    roots: Sequence[Path] = ()
    on_create: Optional[OnCreate] = None
    carried_own: bool = False
    local_files: Optional[Path] = None
    keep_unresolved: bool = False
    dry_run: bool = False
    decide_only: bool = False
    copied: Dict[str, str] = field(default_factory=dict)
    actions: List[Tuple[str, str]] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)

    @property
    def files_root(self) -> Path:
        return Path(self.state).joinpath(*FILES_DIR)

    def rewrite_message(self, parts: Any, text: Any, old_item: int, new_item: int, select: Optional[Select] = None) -> Tuple[Any, Any]:
        if not isinstance(parts, str) or not parts:
            return parts, text
        try:
            doc = json.loads(parts)
        except ValueError:
            return parts, text
        before = len(self.dropped)
        self.rewrite(doc, old_item, new_item, select)
        lost = self.dropped[before:]
        new_text = text
        for name in lost:
            line = NOT_HERE_LINE.format(name=name)
            new_text = f"{new_text}\n{line}" if new_text else line
        return ("" if doc == {"files": []} and lost else json.dumps(doc, separators=(", ", ": "), ensure_ascii=False)), new_text

    def rewrite(self, node: Any, old_item: int, new_item: int, select: Optional[Select] = None) -> Any:
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if key in _FILES_KEYS and isinstance(value, list):
                    node[key] = [e for e in (self._entry(e, old_item, new_item, select) for e in value) if e is not None]
                else:
                    self.rewrite(value, old_item, new_item, select)
        elif isinstance(node, list):
            for value in node:
                self.rewrite(value, old_item, new_item, select)
        return node

    def _entry(self, entry: Any, old_item: int, new_item: int, select: Optional[Select]) -> Optional[Any]:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or (select is not None and not select(entry)):
            return entry
        own = _RELATIVE.match(path)
        if own is not None and self.carried_own and int(own.group(1)) == int(old_item):
            entry["path"] = f"{REL_PREFIX}/{int(new_item)}/{own.group(2)}"
            return entry
        copied = self._copy_in(entry, path, new_item)
        if copied is not None:
            entry["path"] = copied
            return entry
        name = str(entry.get("name") or os.path.basename(path))
        if self.keep_unresolved:
            self.unresolved.append(name)
            return entry
        self.dropped.append(name)
        return None

    def _source_problem(self, path: str, file_id: str, item_id: int) -> Tuple[Optional[Path], Optional[str]]:
        if os.path.isabs(path):
            return Path(path), task_folders.task_file_problem(Path(path), self.roots, file_id)
        found = _RELATIVE.match(path)
        if found is None or self.local_files is None:
            return None, "its bytes are not carried"
        source = Path(self.local_files) / found.group(1) / found.group(2)
        if not task_folders.FILE_ID_PATTERN.match(file_id) or not source.name.startswith(f"{file_id}-") or ".." in found.group(2).split("/"):
            return None, "its name is not a stored file's"
        return source, (None if task_folders.is_regular_file(source) and task_folders.is_real_dir(source.parent) else "it is not a regular file")

    def _copy_in(self, entry: Dict[str, Any], path: str, new_item: int) -> Optional[str]:
        file_id = str(entry.get("id") or "")
        source, why = self._source_problem(path, file_id, new_item)
        if source is None or why is not None:
            self._log_not_copied(why, os.path.basename(path))
            return None
        dest = self.files_root / str(int(new_item)) / source.name
        if self.decide_only:
            return f"{REL_PREFIX}/{int(new_item)}/{source.name}"
        try:
            sha, length = _hash_of(str(source))
            if os.path.lexists(dest):
                if _hash_of(str(dest)) != (sha, length):
                    raise PlaceConflict(str(dest))
            else:
                if not self.dry_run:
                    if self.on_create is not None:
                        self.on_create(dest, sha, length)
                    dest.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
                    write_verified(_chunks(str(source)), dest, length=length, sha256=sha, mode=FILE_MODE)
                    self.copied[str(dest)] = sha
                if (str(source), str(dest)) not in self.actions:
                    self.actions.append((str(source), str(dest)))
        except (OSError, PlaceConflict, PlaceMismatch) as exc:
            self._log_not_copied(type(exc).__name__, source.name)
            return None
        return f"{REL_PREFIX}/{int(new_item)}/{source.name}"

    def _log_not_copied(self, reason: Optional[str], name: str) -> None:
        log = logger.debug if self.decide_only else logger.warning
        log("task_file_reference_not_copied", reason=reason, name=name, decide_only=self.decide_only)


def names_files(parts: Any) -> bool:
    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            return any((key in _FILES_KEYS and isinstance(v, list) and bool(v)) or walk(v) for key, v in node.items())
        return isinstance(node, list) and any(walk(v) for v in node)

    if not isinstance(parts, str) or not parts:
        return False
    try:
        return walk(json.loads(parts))
    except ValueError:
        return False
    except RecursionError:
        return True


def _chunks(path: str) -> Iterator[bytes]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd, "rb", closefd=False) as handle:
            while True:
                block = handle.read(_BLOCK)
                if not block:
                    return
                yield block
    finally:
        os.close(fd)


def _hash_of(path: str) -> Tuple[str, int]:
    digest, length = hashlib.sha256(), 0
    for block in _chunks(path):
        digest.update(block)
        length += len(block)
    return digest.hexdigest(), length


def remove_copies(state: Path, copies: Mapping[str, str]) -> int:
    root, removed = Path(state).joinpath(*FILES_DIR), 0
    for text, sha in copies.items():
        path = Path(text)
        try:
            if root not in path.parents or not task_folders.is_regular_file(path) or _hash_of(text)[0] != sha:
                continue
            path.unlink()
            removed += 1
            path.parent.rmdir()
        except OSError as exc:
            logger.info("task_file_copy_kept", path=text, error_type=type(exc).__name__)
    return removed
