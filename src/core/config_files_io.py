from __future__ import annotations

import os
from pathlib import Path

from src.core.test_write_guard import assert_test_write_allowed
from src.core.unique_tmp_path import unique_tmp_path
from src.core.config_files_constants import (
    READONLY_COLLAPSED_DIRS,
    SENSITIVE_NAMES,
    SENSITIVE_PREFIXES,
    SENSITIVE_SUFFIXES,
    EXECUTABLE_EXTENSIONS,
    EXECUTABLE_DIRS,
)


def is_sensitive_name(name: str) -> bool:
    if name in SENSITIVE_NAMES:
        return True
    if any(name.startswith(p) for p in SENSITIVE_PREFIXES):
        return True
    return any(name.endswith(s) for s in SENSITIVE_SUFFIXES)


def classify(root: Path, path: Path) -> tuple[bool, bool, bool]:
    """
    Description: compute (is_executable, is_sensitive, read_only) for one
      path relative to its root. The SINGLE source of these three
      judgements - read, write and create all call this, so a file cannot
      be treated as ordinary by one path and executable by another.

      Note ``is_executable`` and ``is_sensitive`` are False for a path
      that does not exist yet in the ``path.is_file()`` sense; creation
      therefore evaluates them on NAME and LOCATION only, which is
      deliberate - a hook that does not exist yet is still going to run
      once it does.
    Inputs: root (Path); path (Path) - must be inside root.
    Output: tuple[bool, bool, bool].
    """
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = ()
    top = rel_parts[0] if rel_parts else ""
    read_only = top in READONLY_COLLAPSED_DIRS
    in_executable_dir = any(part in EXECUTABLE_DIRS for part in rel_parts[:-1])
    is_executable = path.suffix in EXECUTABLE_EXTENSIONS and in_executable_dir
    is_sensitive = is_sensitive_name(path.name)
    if path.is_dir():
        is_executable = False
        is_sensitive = False
    return is_executable, is_sensitive, read_only


def atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    assert_test_write_allowed(path)

    tmp_path = unique_tmp_path(path)
    try:
        if mode is None:
            handle = open(tmp_path, "w", encoding="utf-8")
        else:
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            try:
                os.fchmod(fd, mode)
            except OSError:
                os.close(fd)
                raise
            handle = os.fdopen(fd, "w", encoding="utf-8")
        with handle as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
