
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Dict

import structlog

from src.core.json_artifact import atomic_write_json
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

LEGACY_DIR_NAME = "addons"
NEW_DIR_NAME = "cplugs"
MARKER = ".moved-to-cplugs"
_SIDE_SUFFIXES = ("-wal", "-shm", "-journal")


def _fsync_file(path: Path) -> None:
    with open(path, "rb") as handle:
        os.fsync(handle.fileno())


def _copy_db(src: Path, dest: Path) -> None:
    source = sqlite3.connect(str(src), timeout=5.0)
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
    finally:
        source.close()
    _fsync_file(dest)


def _copy_json(src: Path, dest: Path, top_level: bool) -> bool:
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if top_level and src.name == "state.json" and "addons" in data and "cplugs" not in data:
        data = {("cplugs" if k == "addons" else k): v for k, v in data.items()}
    if not atomic_write_json(dest, data, log_event="cplug_state_move_json_failed"):
        raise OSError(f"could not write {dest}")
    return True


def _copy_tree(src: Path, dest: Path, counts: Dict[str, int]) -> None:
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        name = path.name
        if name.endswith(_SIDE_SUFFIXES) and path.with_name(name.rsplit("-", 1)[0]).exists():
            continue
        if name.endswith(".db"):
            _copy_db(path, target)
            counts["db"] += 1
        elif name.endswith(".json") and _copy_json(path, target, top_level=len(rel.parts) == 1):
            counts["json"] += 1
        else:
            shutil.copyfile(path, target)
            _fsync_file(target)
            counts["other"] += 1


def _verify(src: Path, dest: Path) -> None:
    for path in src.rglob("*"):
        if not path.is_file() or path.name.endswith(_SIDE_SUFFIXES) and path.with_name(path.name.rsplit("-", 1)[0]).exists():
            continue
        target = dest / path.relative_to(src)
        if not target.is_file():
            raise OSError(f"missing after copy: {target}")
        if path.name.endswith(".db"):
            conn = sqlite3.connect(str(target))
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise OSError(f"integrity check failed: {target}")
            finally:
                conn.close()
        elif not path.name.endswith(".json") and path.stat().st_size != target.stat().st_size:
            raise OSError(f"size differs after copy: {target}")


def move_legacy_state(state_dir: Path) -> str:
    old = Path(state_dir) / LEGACY_DIR_NAME
    new = Path(state_dir) / NEW_DIR_NAME
    if not old.is_dir():
        return "none"
    if (old / MARKER).exists():
        return "done"
    if new.exists():
        logger.warning("cplug_state_legacy_ignored", legacy=str(old), current=str(new))
        return "ignored"
    assert_test_write_allowed(new)
    temp = Path(state_dir) / f".{NEW_DIR_NAME}.moving"
    if temp.exists():
        shutil.rmtree(temp)
    counts = {"db": 0, "json": 0, "other": 0}
    try:
        temp.mkdir(parents=True)
        _copy_tree(old, temp, counts)
        _verify(old, temp)
        os.replace(temp, new)
    except (OSError, sqlite3.Error) as exc:
        logger.error("cplug_state_move_failed", error_type=type(exc).__name__, error=str(exc)[:300])
        shutil.rmtree(temp, ignore_errors=True)
        raise
    try:
        (old / MARKER).write_text("moved to cplugs/; kept as a record\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("cplug_state_marker_unwritten", error_type=type(exc).__name__)
    logger.info("cplug_state_moved", source=str(old), target=str(new), source_kept=True, **counts)
    return "moved"
