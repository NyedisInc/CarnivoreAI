
from __future__ import annotations

import os
import time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core import project_directory

MAX_ENTRIES = 500
MAX_SCANNED = 5000
MAX_PATH_CHARS = 4096
SCAN_BUDGET_SECONDS = 2.0
HIDDEN_TOP_LEVEL = frozenset({"library"})


class FolderEntry(BaseModel):
    """One listed folder: its name and its canonical path."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=255)
    path: str = Field(max_length=MAX_PATH_CHARS)


class FolderListing(BaseModel):
    """A folder and its child folders; ``parent`` is None at a root; ``truncated`` when a cap cut the list short."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=MAX_PATH_CHARS)
    parent: Optional[str] = Field(default=None, max_length=MAX_PATH_CHARS)
    entries: List[FolderEntry] = Field(default_factory=list, max_length=MAX_ENTRIES)
    truncated: bool = False


class FolderBrowseRefused(Exception):

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


_INVALID = (400, "invalid_path", "that is not a usable folder path")
_OUTSIDE = (403, "outside_allowed_roots", "that folder is outside the places projects may be created")
_MISSING = (404, "not_found", "that folder does not exist")
_UNREADABLE = (409, "unreadable", "that folder cannot be read")


def is_browsable(path: str, roots: "list[str]") -> bool:
    for root in roots:
        if not project_directory.within_roots(path, [root]):
            continue
        parts = [part for part in os.path.relpath(path, root).split(os.sep) if part not in ("", ".")]
        if parts and parts[0].lower() in HIDDEN_TOP_LEVEL:
            continue
        if not any(part.startswith(".") for part in parts):
            return True
    return False


def list_project_folders(path: Optional[str], settings=None) -> FolderListing:
    if path is not None and (not path.strip() or len(path) > MAX_PATH_CHARS or "\x00" in path):
        raise FolderBrowseRefused(*_INVALID)
    roots = project_directory.allowed_roots(settings)
    try:
        target = project_directory.canonical_path(path) if path is not None else project_directory.projects_root(settings)
    except (OSError, ValueError):
        raise FolderBrowseRefused(*_INVALID) from None
    if not is_browsable(target, roots):
        raise FolderBrowseRefused(*_OUTSIDE)
    if not os.path.isdir(target):
        raise FolderBrowseRefused(*_MISSING)
    names, truncated = _child_folders(target)
    entries: List[FolderEntry] = []
    for name, child_path in names:
        try:
            real = project_directory.canonical_path(child_path)
        except (OSError, ValueError):
            continue
        if is_browsable(real, roots):
            entries.append(FolderEntry(name=name, path=real))
    parent = os.path.dirname(target)
    if parent == target or not is_browsable(parent, roots):
        parent = None
    return FolderListing(path=target, parent=parent, entries=entries, truncated=truncated)


def _child_folders(target: str) -> "tuple[list[tuple[str, str]], bool]":
    kept: List["tuple[str, str]"] = []
    truncated = False
    deadline = time.monotonic() + SCAN_BUDGET_SECONDS
    try:
        with os.scandir(target) as it:
            for scanned, child in enumerate(it, start=1):
                if scanned > MAX_SCANNED or time.monotonic() > deadline:
                    truncated = True
                    break
                if child.name.startswith("."):
                    continue
                try:
                    if child.is_dir():
                        kept.append((child.name, child.path))
                except OSError:
                    continue
    except OSError:
        raise FolderBrowseRefused(*_UNREADABLE) from None
    kept.sort(key=lambda item: item[0].lower())
    if len(kept) > MAX_ENTRIES:
        kept, truncated = kept[:MAX_ENTRIES], True
    return kept, truncated
