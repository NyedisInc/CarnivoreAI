"""The ``.cc.theme`` file format: where it lives, how it is read and written.

Slice S2 of the ``session_manager`` decomposition. Split out of
``theme_store`` because it holds NO STATE: three functions over one
single-line file. Keeping it stateless is what lets ``ThemeStore`` stay a
class about the mutable pin map, and it keeps both modules under the
package's 500-line rule.

``<working_dir>/.cc.theme`` is the v0.7.0+ source of truth for a
project's theme, superseding the per-tmux-name ``pinned_themes.json``
map. It is keyed by DIRECTORY, which is the whole point: two browsers on
two machines pointed at the same checkout converge on the same theme
without round-tripping a per-machine cache. The file is one line, the
theme id plus a trailing newline.

**THE WRITE RAISES AND THE PIN-MAP WRITE DOES NOT, DELIBERATELY.** This
one is reached from a user action that has a response to fail, so a write
that did not happen must not report success. ``ThemeStore.save`` is
reached from destroy and rename cleanup, where raising would break a path
the user is waiting on to do something else.
"""

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
    """Atomically write or clear ``<working_dir>/.cc.theme``.

    Description: an empty or None ``theme_id`` deletes the dotfile.
      Otherwise writes ``<theme_id>\\n`` at mode 0o644 through
      temp-then-``os.replace``, so a crash mid-write can never leave a
      half-written file at the canonical path.
    Inputs: working_dir (str | Path) - must exist and be a directory.
      theme_id (str | None) - the theme, None or empty to clear.
    Output: None.
    Raises: ValueError when ``working_dir`` is unresolvable,
      FileNotFoundError when it does not exist, NotADirectoryError when
      it is not a directory, OSError when the write or the unlink fails.
    Example: write_project_theme(project, "metal")
    """
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
