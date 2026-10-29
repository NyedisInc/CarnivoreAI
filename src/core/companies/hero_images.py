
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import structlog

from src.config import settings
from src.core.terminal_background import CONTENT_TYPES
from src.core.unique_tmp_path import unique_tmp_path

logger = structlog.get_logger()

COMPANY = "company"
PROJECT = "project"
_DIRS = {COMPANY: "company_images", PROJECT: "project_images"}
GENERATED_DIR = "generated"
_INDEX_CACHE: Dict[str, Tuple[tuple, Dict[int, str]]] = {}
_INDEX_LOCK = threading.Lock()
_FAIL_CACHE: Dict[Tuple[str, int], Tuple[tuple, Dict[str, object]]] = {}


def images_dir(kind: str) -> Path:
    return settings.get_state_dir() / _DIRS[kind]


def generated_dir(kind: str) -> Path:
    return images_dir(kind) / GENERATED_DIR


def _find_in(directory: Path, row_id: int) -> Optional[Path]:
    for ext in CONTENT_TYPES:
        candidate = directory / f"{int(row_id)}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def find_upload(kind: str, row_id: int) -> Optional[Path]:
    return _find_in(images_dir(kind), row_id)


def find(kind: str, row_id: int) -> Optional[Path]:
    return find_upload(kind, row_id) or _find_in(generated_dir(kind), row_id)


def rev_of(path: Path) -> Optional[str]:
    try:
        return str(path.stat().st_mtime_ns)
    except OSError:
        return None


def fields(kind: str, row_id: Optional[int]) -> Dict[str, object]:
    path = find(kind, row_id) if row_id is not None else None
    rev = rev_of(path) if path is not None else None
    return {"has_image": rev is not None, "image_rev": rev}


def index(kind: str) -> Dict[int, str]:
    stamp = tuple(_folder_stamp(d) for d in (generated_dir(kind), images_dir(kind)))
    with _INDEX_LOCK:
        hit = _INDEX_CACHE.get(kind)
    if hit is not None and hit[0] == stamp:
        return dict(hit[1])
    found = _scan(kind)
    with _INDEX_LOCK:
        _INDEX_CACHE[kind] = (stamp, found)
    return dict(found)


def fail_note_path(kind: str, row_id: int) -> Path:
    return generated_dir(kind) / f"{int(row_id)}.fail.json"


def read_fail_note(kind: str, row_id: int) -> Dict[str, object]:
    path = fail_note_path(kind, row_id)
    try:
        st = path.stat()
        stamp: tuple = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    except OSError:
        stamp = ()
    key = (kind, int(row_id))
    with _INDEX_LOCK:
        hit = _FAIL_CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return dict(hit[1])
    note: Dict[str, object] = {}
    if stamp:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            note = parsed if isinstance(parsed, dict) else {}
        except (OSError, ValueError):
            note = {}
    with _INDEX_LOCK:
        _FAIL_CACHE[key] = (stamp, note)
    return dict(note)


def invalidate_fail_note(kind: str, row_id: int) -> None:
    with _INDEX_LOCK:
        _FAIL_CACHE.pop((kind, int(row_id)), None)


def _folder_stamp(directory: Path) -> tuple:
    try:
        st = directory.stat()
    except OSError:
        return (str(directory),)
    return (str(directory), st.st_ino, st.st_mtime_ns)


def _scan(kind: str) -> Dict[int, str]:
    found: Dict[int, str] = {}
    for directory in (generated_dir(kind), images_dir(kind)):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            stem, _, ext = path.name.rpartition(".")
            if ext in CONTENT_TYPES and stem.isdigit():
                rev = rev_of(path)
                if rev is not None:
                    found[int(stem)] = rev
    return found


def attach(kind: str, rows: list) -> None:
    revs = index(kind)
    for row in rows:
        rev = revs.get(row.get("id"))
        row["has_image"] = rev is not None
        row["image_rev"] = rev


def _unlink_row(directory: Path, row_id: int, suffixes: Tuple[str, ...]) -> None:
    for suffix in suffixes:
        candidate = directory / f"{int(row_id)}.{suffix}"
        try:
            candidate.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("hero_image_unlink_failed", path=str(candidate), error=str(exc))


def remove_upload(kind: str, row_id: int) -> None:
    _unlink_row(images_dir(kind), row_id, tuple(CONTENT_TYPES))
    for thumb in (images_dir(kind) / "thumbs").glob(f"{int(row_id)}-*.webp"):
        thumb.unlink(missing_ok=True)


def remove(kind: str, row_id: int) -> None:
    remove_upload(kind, row_id)
    _unlink_row(generated_dir(kind), row_id, tuple(CONTENT_TYPES) + ("prompt.json", "fail.json"))
    invalidate_fail_note(kind, row_id)


def store(kind: str, row_id: int, ext: str, data: bytes) -> Tuple[Path, Optional[str]]:
    target = images_dir(kind) / f"{int(row_id)}.{ext}"
    atomic_write(target, data)
    for other in CONTENT_TYPES:
        if other != ext:
            (target.parent / f"{int(row_id)}.{other}").unlink(missing_ok=True)
    _pregenerate_thumbs(kind, row_id, target)
    return target, rev_of(target)


def store_generated(kind: str, row_id: int, ext: str, data: bytes, prompt_record: dict) -> Optional[Path]:
    if find_upload(kind, row_id) is not None:
        return None
    target = generated_dir(kind) / f"{int(row_id)}.{ext}"
    atomic_write(generated_dir(kind) / f"{int(row_id)}.prompt.json", json.dumps(prompt_record, indent=2).encode())
    atomic_write(target, data)
    for other in CONTENT_TYPES:
        if other != ext:
            (target.parent / f"{int(row_id)}.{other}").unlink(missing_ok=True)
    _pregenerate_thumbs(kind, row_id, target)
    return target


def _pregenerate_thumbs(kind: str, row_id: int, original: Path) -> None:
    from src.core.companies import hero_thumbs

    for tier in hero_thumbs.TIERS:
        hero_thumbs.thumb_for(kind, row_id, original, tier)


def atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = unique_tmp_path(target)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(target))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
