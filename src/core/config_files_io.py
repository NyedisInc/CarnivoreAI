from __future__ import annotations

from pathlib import Path

from src.core.test_write_guard import assert_test_write_allowed
from src.core.safe_io.atomic_write import atomic_write_bytes as _atomic_write_bytes, atomic_write_text
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

    atomic_write_text(path, content, mode=mode)


def atomic_write_bytes(path: Path, data: bytes, mode: int) -> None:
    assert_test_write_allowed(path)
    _atomic_write_bytes(path, data, mode=mode)
