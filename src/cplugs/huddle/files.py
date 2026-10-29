
from __future__ import annotations

import errno
import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set

import structlog

from src.cplugs.huddle import rich_ask
from src.cplugs.huddle.rules import TaskManagerFileRemoved, TaskManagerInvalid, TaskManagerNotFound
from src.cplugs.sdk import CplugStorage, task_folders
from src.cplugs.sdk.uploads import is_image_name

logger = structlog.get_logger()

DIR_NAME = "files"
ID_PATTERN = task_folders.FILE_ID_PATTERN
MAX_PER_REPLY = 10
ORPHAN_AGE_S = 86400.0
PARTS_PREFIX = '{"files"'
FREEFORM_PREFIX = rich_ask.ANSWERS_TO_PREFIX
PARTS_SQL = (f"(parts LIKE '{PARTS_PREFIX}%' OR parts LIKE '{FREEFORM_PREFIX}%\"files\"%' "
             "OR parts LIKE '{\"quote\"%\"files\"%')")
QUOTED_PREFIX = '{"quote"'
ASIDE_PREFIX = ".removing-"
ASIDE_GRACE_S = 120.0
DEFAULT_MIME = "application/octet-stream"


def root(storage: CplugStorage) -> Path:
    return storage.path / DIR_NAME


def item_dir(storage: CplugStorage, item_id: int) -> Path:
    return root(storage) / str(int(item_id))


def mime_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or DEFAULT_MIME


def name_of(stored: str) -> str:
    return stored.split("-", 1)[1] if "-" in stored else stored


def disposition(name: str) -> str:
    return "inline" if is_image_name(name) else "attachment"


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def save(storage: CplugStorage, item_id: int, name: str, data: bytes, folder: Optional[Path] = None) -> Dict[str, Any]:
    if folder is None:
        folder = item_dir(storage, item_id)
        _private_dir(root(storage))
    _private_dir(folder)
    file_id = uuid.uuid4().hex[:8]
    target = folder / f"{file_id}-{name}"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return {"id": file_id, "name": name, "mime": mime_of(name), "size": len(data)}


def _recorded_dirs(storage: CplugStorage, item_id: int, file_id: str) -> List[Path]:
    with closing(storage.connect(False)) as conn:
        try:
            rows = conn.execute(f"SELECT parts FROM work_messages WHERE item_id = ? AND {PARTS_SQL}", (int(item_id),)).fetchall()
        except sqlite3.OperationalError:
            return []
    return [Path(e["path"]).parent for r in rows for e in entries_of(r["parts"])
            if e.get("id") == file_id and isinstance(e.get("path"), str) and os.path.isabs(e["path"])]


def locate(storage: CplugStorage, item_id: int, file_id: str, folders: Sequence[Path] = ()) -> Path:
    if not ID_PATTERN.match(file_id or ""):
        raise TaskManagerNotFound("no such file")
    for folder in _search_folders(storage, item_id, file_id, folders):
        found = _in_folder(folder, file_id)
        if found is not None:
            return found
    raise TaskManagerNotFound("no such file")


def _search_folders(storage: CplugStorage, item_id: int, file_id: str, folders: Sequence[Path]) -> Iterator[Path]:
    yield item_dir(storage, item_id)
    yield from folders
    yield from _recorded_dirs(storage, item_id, file_id)


def aside_name(path: Path) -> Path:
    return path.with_name(f"{ASIDE_PREFIX}{path.name}")


def leftovers(storage: CplugStorage, item_id: int, file_id: str, folders: Sequence[Path] = ()) -> List[Path]:
    if not ID_PATTERN.match(file_id or ""):
        return []
    found: List[Path] = []
    for folder in _search_folders(storage, item_id, file_id, folders):
        if not folder.is_symlink() and folder.is_dir():
            found.extend(p for p in folder.glob(f"{ASIDE_PREFIX}{file_id}-*") if p.is_file() and not p.is_symlink())
    return found


def candidates(storage: CplugStorage, item_id: int, file_id: str, folders: Sequence[Path] = ()) -> List[Path]:
    if not ID_PATTERN.match(file_id or ""):
        return []
    found: List[Path] = []
    for folder in _search_folders(storage, item_id, file_id, folders):
        if not folder.is_symlink() and folder.is_dir():
            found.extend(folder.glob(f"{file_id}-*"))
    return list(dict.fromkeys(found))


def _in_folder(folder: Path, file_id: str) -> Optional[Path]:
    if folder.is_symlink() or not folder.is_dir():
        return None
    found = sorted(folder.glob(f"{file_id}-*"))
    if not found or found[0].is_symlink() or not found[0].is_file():
        return None
    return found[0]


def mismatch(path: Path, file_id: str, name: str, size: int, sha256: Optional[str]) -> Optional[str]:
    if path.name != f"{file_id}-{name}":
        return "the stored file has another name than the board recorded"
    if path.stat().st_size != size:
        return "the stored file has another size than the board recorded"
    if sha256 is not None and hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        return "the stored file has other content than the board recorded"
    return None


def _stored_path(storage: CplugStorage, path: Path) -> str:
    try:
        return path.relative_to(storage.path).as_posix()
    except ValueError:
        return str(path)


def stamp_now(path: Path) -> None:
    try:
        os.utime(path)
    except OSError as exc:
        logger.warning("task_manager_file_stamp_failed", name=path.name, error=type(exc).__name__)


def move_into(path: Path, folder: Path) -> Path:
    target = folder / path.name
    if os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, "a file of that name is already in the task folder", str(target))
    try:
        os.rename(path, target)
        stamp_now(target)
        return target
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, path.read_bytes())
        os.fsync(fd)
    finally:
        os.close(fd)
    path.unlink()
    return target


def describe(storage: CplugStorage, item_id: int, file_id: str, folders: Sequence[Path] = ()) -> Dict[str, Any]:
    return _entry(storage, file_id, locate(storage, item_id, file_id, folders))


def _entry(storage: CplugStorage, file_id: str, path: Path) -> Dict[str, Any]:
    name = name_of(path.name)
    return {"id": file_id, "name": name, "mime": mime_of(name), "size": path.stat().st_size, "path": _stored_path(storage, path)}


def attach(storage: CplugStorage, item_id: int, file_ids: Sequence[str], target: Optional[Path] = None,
           folders: Sequence[Path] = ()) -> List[Dict[str, Any]]:
    ids = list(dict.fromkeys(file_ids))
    if len(ids) > MAX_PER_REPLY:
        raise TaskManagerInvalid(f"a reply may carry at most {MAX_PER_REPLY} files")
    found = [(i, locate(storage, item_id, i, folders)) for i in ids]
    if target is None or not found:
        return [_entry(storage, i, p) for i, p in found]
    own = item_dir(storage, item_id)
    keep = _referenced(storage)
    out = []
    for file_id, path in found:
        if path.parent == own and f"{int(item_id)}/{file_id}" not in keep:
            path = move_into(path, target)
            logger.info("task_manager_file_moved_to_task_folder", item=item_id, file=file_id)
        elif path.parent != own:
            stamp_now(path)
        out.append(_entry(storage, file_id, path))
    return out


def require_present(storage: CplugStorage, parts: str) -> None:
    for e in entries_of(parts):
        if isinstance(e.get("path"), str) and not (storage.path / e["path"]).is_file():
            raise TaskManagerFileRemoved(f"{e.get('name', e.get('id'))} was removed, so it cannot be attached")


def parts_of(entries: Sequence[Dict[str, Any]]) -> str:
    return json.dumps({"files": list(entries)}, ensure_ascii=False) if entries else ""


def entries_of(raw: str) -> List[Dict[str, Any]]:
    if not raw or not raw.startswith((PARTS_PREFIX, FREEFORM_PREFIX, QUOTED_PREFIX)):
        return []
    try:
        return [dict(e) for e in json.loads(raw).get("files", [])]
    except (ValueError, KeyError, TypeError):
        return []


def wire(raw: str) -> Optional[List[Dict[str, Any]]]:
    out = [{"id": e["id"], "name": e["name"], "mime": e["mime"], "size": e["size"], "image": is_image_name(e["name"]),
            "path": e["path"]} for e in entries_of(raw) if {"id", "name", "mime", "size", "path"} <= e.keys()]
    return out or None


def for_agent(base: Path, entries: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"name": e["name"], "mime": e["mime"], "size": e["size"], "path": str((base / e["path"]).resolve())} for e in entries]


def summary_text(raw: str) -> str:
    return ", ".join(e.get("name", "") for e in entries_of(raw))


def has_messages(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'work_messages'").fetchone() is not None


def _referenced(storage: CplugStorage) -> Set[str]:
    with closing(storage.connect(False)) as conn:
        if not has_messages(conn):
            return set()
        rows = conn.execute(f"SELECT item_id, parts FROM work_messages WHERE {PARTS_SQL}").fetchall()
    return {f"{r['item_id']}/{e['id']}" for r in rows for e in entries_of(r["parts"]) if "id" in e}


def _sweep_one(path: Path, folder: Path, keep: Set[str], at: float, age_s: float) -> int:
    try:
        stored = path.name[len(ASIDE_PREFIX):] if path.name.startswith(ASIDE_PREFIX) else path.name
        if stored.split("-", 1)[0] in keep:
            return 0
        if at - path.stat().st_mtime < (ASIDE_GRACE_S if stored != path.name else age_s):
            return 0
        path.unlink()
    except FileNotFoundError:
        return 0
    return 1


def sweep_orphans(storage: CplugStorage, now: Optional[float] = None, age_s: float = ORPHAN_AGE_S) -> int:
    base = root(storage)
    if not base.is_dir():
        return 0
    at = time.time() if now is None else now
    keep = {ref.split("/", 1)[1] for ref in _referenced(storage)}
    removed = 0
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        for path in sorted(folder.iterdir()):
            removed += _sweep_one(path, folder, keep, at, age_s)
        if not any(folder.iterdir()):
            shutil.rmtree(folder, ignore_errors=True)
    if removed:
        logger.info("task_manager_orphan_files_swept", removed=removed)
    return removed


__all__ = ["ASIDE_GRACE_S", "ASIDE_PREFIX", "aside_name", "attach", "candidates", "leftovers", "describe", "disposition", "entries_of", "for_agent", "item_dir", "locate", "has_messages", "mismatch", "move_into", "parts_of", "require_present", "save",
           "stamp_now", "summary_text", "sweep_orphans", "wire"]
