
from __future__ import annotations

import os
import stat
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import structlog

from src.core.unique_tmp_path import unique_tmp_path

logger = structlog.get_logger()

DOTFILE_NAME = ".cc.theme"

DOTFILE_MAX_BYTES = 1024

_CACHE: Dict[Path, Tuple[Tuple[int, int, int], Optional[str]]] = {}
_CACHE_LOCK = threading.Lock()


def project_theme_path(working_dir) -> Optional[Path]:
    if not working_dir:
        return None
    try:
        return Path(str(working_dir)).expanduser().resolve() / DOTFILE_NAME
    except (OSError, RuntimeError):
        return None


def read_project_theme(working_dir) -> Optional[str]:
    path = project_theme_path(working_dir)
    if path is None:
        return None
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("project_theme_read_failed", path=str(path), error=str(exc))
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > DOTFILE_MAX_BYTES:
            logger.warning("project_theme_read_skipped", path=str(path), size=info.st_size, regular=stat.S_ISREG(info.st_mode))
            return None
        data = os.read(fd, DOTFILE_MAX_BYTES + 1)
    except OSError as exc:
        logger.warning("project_theme_read_failed", path=str(path), error=str(exc))
        return None
    finally:
        os.close(fd)
    if len(data) > DOTFILE_MAX_BYTES:
        logger.warning("project_theme_read_skipped", path=str(path), size=len(data), regular=True)
        return None
    content = data.decode("utf-8", errors="replace").strip()
    return content or None


def read_project_theme_cached(working_dir) -> Optional[str]:
    path = project_theme_path(working_dir)
    if path is None:
        return None
    try:
        info = os.stat(str(path))
    except FileNotFoundError:
        return None
    except OSError:
        return read_project_theme(working_dir)
    identity = (info.st_ino, info.st_size, info.st_mtime_ns)
    with _CACHE_LOCK:
        hit = _CACHE.get(path)
    if hit is not None and hit[0] == identity:
        return hit[1]
    value = read_project_theme(working_dir)
    with _CACHE_LOCK:
        _CACHE[path] = (identity, value)
    return value


def _forget(path: Path) -> None:
    with _CACHE_LOCK:
        _CACHE.pop(path, None)


def write_project_theme(working_dir, theme_id: Optional[str]) -> None:
    path = project_theme_path(working_dir)
    if path is None:
        raise ValueError(f"Invalid working_dir: {working_dir!r}")

    _forget(path)
    parent = path.parent
    if not parent.exists():
        raise FileNotFoundError(f"working_dir does not exist: {parent}")
    if not parent.is_dir():
        raise NotADirectoryError(f"working_dir is not a directory: {parent}")

    if not theme_id:
        if path.exists():
            try:
                path.unlink()
                logger.info("project_theme_cleared", path=str(path))
            except OSError as exc:
                logger.error(
                    "project_theme_clear_failed",
                    path=str(path),
                    error=str(exc),
                )
                raise
        return

    tmp = unique_tmp_path(path)
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(f"{theme_id}\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            os.chmod(str(tmp), 0o644)
        except OSError:
            logger.debug("project_theme_chmod_failed", path=str(tmp))
        os.replace(str(tmp), str(path))
        logger.info("project_theme_set", path=str(path), theme_id=theme_id)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
