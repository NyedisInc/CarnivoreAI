
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core import db
from src.core.json_artifact import atomic_write_json
from src.core.test_write_guard import assert_test_write_allowed
from src.core.work import folders
from src.plugins.sdk.renamed_files import is_bookkeeping, marker_name, moved_list

logger = structlog.get_logger()

MOVING_NAME = ".files.moving"
MARKER_FORMAT = 1
FREE_MARGIN_BYTES = 256 * 1024 * 1024
_CHUNK = 1024 * 1024
PRIVATE_DIR_MODE = 0o700
ALERT_SOURCE = "plugin_registry"
ALERT_TITLE, ALERT_DETAIL = "app_alert.plugin_registry.files_no_space.title", "app_alert.plugin_registry.files_no_space.detail"

Listing = Dict[str, Tuple[str, int]]
FreeSpace = Callable[[Path], int]
AlertSink = Callable[..., Any]


class FilesMoveError(OSError):
    pass


@dataclass
class FilesOutcome:

    state: Dict[str, str] = field(default_factory=dict)
    removed: Dict[str, int] = field(default_factory=dict)
    failed: bool = False


@dataclass
class _Plan:

    files: Listing
    copy: List[str] = field(default_factory=list)
    same: List[str] = field(default_factory=list)
    conflict: List[str] = field(default_factory=list)


def files_dir(state_dir: Path, plugin_id: str) -> Path:
    return Path(state_dir).joinpath(*folders.files_rel(plugin_id).split("/"))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def listing(root: Path) -> Listing:
    out: Listing = {}
    if root.is_symlink() or not root.is_dir():
        return out
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not is_bookkeeping(d) and not (Path(current) / d).is_symlink()]
        for name in names:
            path = Path(current) / name
            if is_bookkeeping(name) or path.is_symlink() or not path.is_file():
                continue
            out[path.relative_to(root).as_posix()] = (sha256_of(path), path.stat().st_size)
    return out


def fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _at(root: Path, rel: str) -> Path:
    return root.joinpath(*rel.split("/"))


def _plan(src: Path, dest: Path) -> _Plan:
    plan = _Plan(listing(src))
    for rel, (sha, _size) in sorted(plan.files.items()):
        there = _at(dest, rel)
        if not os.path.lexists(there):
            plan.copy.append(rel)
        elif there.is_file() and not there.is_symlink() and sha256_of(there) == sha:
            plan.same.append(rel)
        else:
            plan.conflict.append(rel)
    return plan


def _copy_in(src: Path, dest: Path, plan: _Plan) -> List[str]:
    temp = dest.parent / MOVING_NAME
    temp.mkdir(mode=PRIVATE_DIR_MODE, parents=True)
    placed: List[str] = []
    try:
        for rel in plan.copy:
            staged = _at(temp, rel)
            staged.parent.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
            shutil.copy2(_at(src, rel), staged, follow_symlinks=False)
            with open(staged, "rb") as handle:
                os.fsync(handle.fileno())
            if sha256_of(staged) != plan.files[rel][0]:
                raise FilesMoveError(f"the copy of {rel} differs from the source")
            target = _at(dest, rel)
            target.parent.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
            if os.path.lexists(target):
                (plan.same if target.is_file() and sha256_of(target) == plan.files[rel][0] else plan.conflict).append(rel)
                continue
            os.replace(staged, target)
            fsync_dir(target.parent)
            placed.append(rel)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return placed


def _write_marker(src: Path, new_id: str, files: Listing) -> bool:
    payload = {"format": MARKER_FORMAT, "to": folders.files_rel(new_id), "moved_at": datetime.now(timezone.utc).isoformat(),
               "bytes": sum(size for _sha, size in files.values()), "files": {rel: sha for rel, (sha, _size) in files.items()}}
    return atomic_write_json(src / marker_name(new_id), payload, log_event="cplug_renamed_files_marker_failed")


def _lost(src: Path, dest: Path, listed: Mapping[str, str]) -> int:
    safe = [rel for rel in listed if rel and ".." not in rel.split("/") and not rel.startswith("/")]
    return sum(1 for rel in safe if _at(src, rel).is_file() and not os.path.lexists(_at(dest, rel)))


def _trusted_marker(src: Path, dest: Path, old: str, new: str) -> bool:
    marker = src / marker_name(new)
    if not marker.exists():
        return False
    listed = moved_list(marker)
    lost = _lost(src, dest, listed) if listed is not None else -1
    if lost == 0:
        return True
    aside = src / f"{marker.name}.stale-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    os.replace(marker, aside)
    logger.error("cplug_renamed_files_marker_stale", old=old, new=new, lost=lost, set_aside=aside.name,
                 reason="unreadable" if listed is None else "listed files are missing from the new folder")
    return False


def _free_bytes(state_dir: Path) -> int:
    return int(shutil.disk_usage(state_dir).free)


def _alert_key(new_id: str) -> str:
    return f"plugin_files.no_space.{new_id}"


def _alert_no_space(sink: AlertSink, state_dir: Path, new_id: str, need: int, free: int) -> None:
    sink(_alert_key(new_id), source=ALERT_SOURCE, severity="error", title_key=ALERT_TITLE, detail_key=ALERT_DETAIL,
         params={"plugin": new_id, "need_mb": need // (1024 * 1024) + 1, "free_mb": free // (1024 * 1024)},
         db_path=db.db_path_for(state_dir))


def _resolve_no_space(state_dir: Path, new_id: str) -> None:
    from src.core.app_alerts import service

    path = db.db_path_for(state_dir)
    if path.exists():
        service.resolve(_alert_key(new_id), db_path=path)


def _merge(state_dir: Path, src: Path, dest: Path, names: Tuple[str, str], free_space: FreeSpace, alert: AlertSink) -> str:
    old, new = names
    plan = _plan(src, dest)
    size = sum(plan.files[rel][1] for rel in plan.copy)
    free = free_space(state_dir)
    if free < size + FREE_MARGIN_BYTES:
        logger.error("cplug_renamed_files_no_space", old=old, new=new, need_bytes=size + FREE_MARGIN_BYTES, free_bytes=free)
        _alert_no_space(alert, state_dir, new, size + FREE_MARGIN_BYTES, free)
        return "no_space"
    logger.info("cplug_renamed_files_started", old=old, new=new, files=len(plan.copy), bytes=size)
    placed = _copy_in(src, dest, plan) if plan.copy else []
    if plan.conflict:
        logger.warning("cplug_renamed_files_conflict", old=old, new=new, files=len(plan.conflict), sample=plan.conflict[:5],
                       reason="a same-name file in the new folder differs; the new folder's file wins, the old one is kept on disk")
    verified = {rel: plan.files[rel] for rel in [*placed, *plan.same]}
    if not _write_marker(src, new, verified):
        return "failed"
    logger.info("cplug_renamed_files_moved", old=old, new=new, files=len(placed), already=len(plan.same), source_kept=True)
    return "moved" if placed or not plan.same else "adopted"


def _move_one(state_dir: Path, old: str, new: str, free_space: FreeSpace, alert: AlertSink) -> str:
    src, dest = files_dir(state_dir, old), files_dir(state_dir, new)
    temp = dest.parent / MOVING_NAME
    if os.path.lexists(temp):
        assert_test_write_allowed(temp)
        shutil.rmtree(temp)
    if src.is_symlink() or not src.is_dir():
        return "none"
    if _trusted_marker(src, dest, old, new):
        _resolve_no_space(state_dir, new)
        return "done"
    assert_test_write_allowed(dest)
    state = _merge(state_dir, src, dest, (old, new), free_space, alert)
    if state in ("moved", "adopted"):
        _resolve_no_space(state_dir, new)
    return state


def configured_renames() -> Dict[str, str]:
    from src.plugins.host.renamed_entry import configured_renames as renames

    return renames()


def migrate(state_dir: Path, renames: Optional[Mapping[str, str]] = None, *, free_space: FreeSpace = _free_bytes,
            alert: Optional[AlertSink] = None) -> FilesOutcome:
    pairs = dict(configured_renames() if renames is None else renames)
    if alert is None:
        from src.core.app_alerts.service import raise_alert

        alert = raise_alert
    outcome = FilesOutcome()
    for old, new in pairs.items():
        try:
            outcome.state[old] = _move_one(Path(state_dir), old, new, free_space, alert)
        except OSError as exc:
            outcome.state[old], outcome.failed = "failed", True
            logger.error("cplug_renamed_files_failed", old=old, new=new, error_type=type(exc).__name__, error=str(exc)[:300])
        outcome.failed = outcome.failed or outcome.state[old] in ("no_space", "failed")
    return outcome
