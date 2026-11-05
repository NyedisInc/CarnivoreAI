
from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Set

import structlog

from src.cplugs.huddle import files, kinds
from src.cplugs.huddle.rules import JOE, TaskManagerError, TaskManagerInvalid
from src.cplugs.sdk import CplugStorage

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

logger = structlog.get_logger()

DIR_NAME = "inbox-files"
STAGED_TTL_S = files.ORPHAN_AGE_S
ENTRY_TTL_S = files.ORPHAN_AGE_S
MAX_PER_ENTRY = files.MAX_PER_REPLY


def _root(storage: CplugStorage) -> Path:
    return storage.path / DIR_NAME


def staged_dir(storage: CplugStorage, list_key: str) -> Path:
    return _root(storage) / "staged" / hashlib.sha256(list_key.encode("utf-8")).hexdigest()[:16]


def entry_dir(storage: CplugStorage, entry_id: int) -> Path:
    return _root(storage) / f"entry-{int(entry_id)}"


def stage(storage: CplugStorage, list_key: str, name: str, data: bytes) -> Dict[str, Any]:
    return files.save(storage, 0, name, data, folder=staged_dir(storage, list_key))


def _find(folder: Path, file_id: str) -> Optional[Path]:
    if not files.ID_PATTERN.match(file_id or "") or not folder.is_dir():
        return None
    return next((p for p in sorted(folder.iterdir()) if p.is_file() and p.name.startswith(f"{file_id}-")), None)


def resolve_staged(storage: CplugStorage, list_key: str, file_ids: Sequence[str], now: Optional[float] = None) -> List[Path]:
    ids = list(dict.fromkeys(file_ids))
    if len(ids) > MAX_PER_ENTRY:
        raise TaskManagerInvalid(f"an entry may carry at most {MAX_PER_ENTRY} files")
    at = time.time() if now is None else now
    out: List[Path] = []
    for file_id in ids:
        path = _find(staged_dir(storage, list_key), file_id)
        if path is None or at - path.stat().st_mtime > STAGED_TTL_S:
            raise TaskManagerInvalid(f"file {file_id} is not a staged file of this list (unknown, another list's, or expired)")
        out.append(path)
    return out


def carry(storage: CplugStorage, entry_id: int, paths: Sequence[Path]) -> None:
    if not paths:
        return
    folder = entry_dir(storage, entry_id)
    files.private_dir(folder)
    for path in paths:
        os.replace(path, folder / path.name)


def uncarry(storage: CplugStorage, entry_id: int, paths: Sequence[Path]) -> None:
    folder = entry_dir(storage, entry_id)
    for path in paths:
        moved = folder / path.name
        if moved.exists():
            try:
                os.replace(moved, path)
            except OSError as exc:
                logger.error("task_manager_inbox_files_uncarry_failed", entry=entry_id, file=path.name, error=str(exc))
    try:
        folder.rmdir()
    except OSError:
        pass


def listing(storage: CplugStorage, entry_id: int) -> List[Dict[str, Any]]:
    folder = entry_dir(storage, entry_id)
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(p for p in folder.iterdir() if p.is_file()):
        name = files.name_of(path.name)
        out.append({"id": path.name.split("-", 1)[0], "name": name, "mime": files.mime_of(name), "size": path.stat().st_size, "path": str(path)})
    return out


def attach_paths(store: "TaskManagerStore", item_id: int, paths: Sequence[Path], pastes: Optional[Path] = None) -> int:
    if not paths:
        return 0
    storage = store.storage
    try:
        target = files.item_dir(storage, item_id)
        files.private_dir(files.root(storage))
        files.private_dir(target)
        for path in paths:
            copy = target / path.name
            shutil.copyfile(path, copy)
            copy.chmod(0o600)
        entries = files.attach(storage, item_id, [p.name.split("-", 1)[0] for p in paths], pastes)
        try:
            store.post(item_id, "", actor=JOE, kind=kinds.COMMENT, parts=files.parts_of(entries), allow_blank=True)
        except (OSError, TaskManagerError):
            logger.error("task_manager_inbox_files_orphaned_after_failed_post", item=item_id, paths=[e.get("path") for e in entries])
            raise
    except (OSError, TaskManagerError) as exc:
        names = ", ".join(files.name_of(p.name) for p in paths)
        logger.error("task_manager_inbox_files_attach_failed", item=item_id, files=names, error=str(exc))
        try:
            store.post(item_id, f"could not attach the file(s) pasted with this entry: {names}", actor=JOE, kind=kinds.COMMENT)
        except (OSError, TaskManagerError) as note_exc:
            logger.error("task_manager_inbox_files_note_failed", item=item_id, files=names, error=str(note_exc))
        return 0
    return len(paths)


def attach_to_item(store: "TaskManagerStore", entry_id: int, item_id: int, pastes: Optional[Callable[[int], Optional[Path]]] = None) -> int:
    folder = entry_dir(store.storage, entry_id)
    carried = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    return attach_paths(store, item_id, carried, pastes(item_id) if pastes and carried else None)


def discard(paths: Sequence[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def sweep(storage: CplugStorage, keep: Set[int], now: Optional[float] = None) -> int:
    base = _root(storage)
    if not base.is_dir():
        return 0
    at = time.time() if now is None else now
    removed = 0
    staged = base / "staged"
    for folder in sorted(p for p in staged.iterdir() if p.is_dir()) if staged.is_dir() else []:
        for path in sorted(p for p in folder.iterdir() if p.is_file()):
            if at - _mtime(path) > STAGED_TTL_S:
                removed += _unlink(path)
        if not any(folder.iterdir()):
            _rmdir(folder)
    for folder in sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("entry-")):
        suffix = folder.name.split("-", 1)[1]
        if not suffix.isdigit():
            logger.debug("task_manager_inbox_files_sweep_skipped", folder=folder.name)
            continue
        if int(suffix) in keep or at - _mtime(folder) <= ENTRY_TTL_S:
            continue
        removed += sum(_unlink(p) for p in sorted(folder.iterdir()) if p.is_file())
        _rmdir(folder)
    if removed:
        logger.info("task_manager_inbox_files_swept", removed=removed)
    return removed


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError as exc:
        logger.debug("task_manager_inbox_files_stat_failed", path=path.name, error=str(exc))
        return time.time()


def _unlink(path: Path) -> int:
    try:
        path.unlink()
    except FileNotFoundError:
        return 0
    except OSError as exc:
        logger.warning("task_manager_inbox_files_unlink_failed", file=path.name, error=str(exc))
        return 0
    return 1


def _rmdir(folder: Path) -> None:
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        logger.warning("task_manager_inbox_files_rmdir_failed", folder=folder.name, error=str(exc))


__all__ = ["ENTRY_TTL_S", "attach_paths", "attach_to_item", "carry", "discard", "entry_dir", "listing", "resolve_staged", "stage", "staged_dir", "sweep", "uncarry"]
