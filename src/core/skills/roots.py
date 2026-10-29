
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.core.sessions.ports import Target

ROOT_OK = "ok"
ROOT_ABSENT = "root_absent"
ROOT_IS_SYMLINK = "root_is_symlink"
ROOT_PARENT_IS_SYMLINK = "root_parent_is_symlink"
TARGET_EXISTS = "target_exists"
TARGET_IS_SYMLINK = "target_is_symlink"

ROOT_STATES: tuple[str, ...] = (
    ROOT_OK,
    ROOT_ABSENT,
    ROOT_IS_SYMLINK,
    ROOT_PARENT_IS_SYMLINK,
    TARGET_EXISTS,
    TARGET_IS_SYMLINK,
)


class UnsafeInstallName(ValueError):
    pass


@dataclass(frozen=True)
class RootCheck:

    harness: str
    root: Path
    state: str

    @property
    def is_writable(self) -> bool:
        return self.state == ROOT_OK


def unsafe_name_reason(name: str) -> str | None:
    if not name or not name.strip():
        return "install name is empty"
    if "\0" in name:
        return f"install name contains a NUL: {name!r}"
    if name.startswith("/") or os.path.isabs(name):
        return f"absolute install name: {name!r}"
    if "\\" in name:
        return (
            f"install name contains a backslash: {name!r}; it is a path "
            "separator on one of the platforms this can run on"
        )
    segments = name.split("/")
    if "" in segments:
        return f"empty path segment in install name: {name!r}"
    if ".." in segments:
        return f"install name escapes with '..': {name!r}"
    if segments[0].startswith("."):
        return (
            f"install name {name!r} starts with a dot; dot directories "
            "under a skills root belong to the harness ('.system') or to "
            "this app ('.carnivore-trash'), never to an installed item"
        )
    return None


def target_dir(target: Target, name: str) -> Path:
    reason = unsafe_name_reason(name)
    if reason is not None:
        raise UnsafeInstallName(reason)
    return target.leaf_dir / name


def symlinked_intermediate(root: Path) -> Optional[Path]:
    for segment in (root.parent,):
        if os.path.lexists(segment) and segment.is_symlink():
            return segment
    return None


def check_root(target: Target, name: str) -> RootCheck:
    destination = target_dir(target, name)
    root = target.leaf_dir

    intermediate = symlinked_intermediate(root)
    if intermediate is not None:
        return RootCheck(
            harness=target.harness, root=root, state=ROOT_PARENT_IS_SYMLINK
        )

    if not os.path.lexists(root):
        return RootCheck(harness=target.harness, root=root, state=ROOT_ABSENT)
    if root.is_symlink():
        return RootCheck(harness=target.harness, root=root, state=ROOT_IS_SYMLINK)

    if os.path.lexists(destination):
        if destination.is_symlink():
            return RootCheck(
                harness=target.harness, root=root, state=TARGET_IS_SYMLINK
            )
        return RootCheck(harness=target.harness, root=root, state=TARGET_EXISTS)

    return RootCheck(harness=target.harness, root=root, state=ROOT_OK)


def check_roots(targets: Iterable[Target], name: str) -> tuple[RootCheck, ...]:
    return tuple(check_root(target, name) for target in targets)
