
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.live_install_roots import (
    AGENTS_DIR_NAME,
    HARNESS_CLAUDE,
    HARNESS_CODEX,
    HARNESS_MOD,
    KIND_SKILL,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
)
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS
from src.core.sessions.ports import InstallRoots, Target
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

SKILL_ROOT_UNSAFE = "skill_root_unsafe"
SKILL_ROOT_FAILED = "skill_root_failed"

ROOT_MODE = 0o700


class RootCreateRefused(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _under(leaf: Path, boundary: Path) -> bool:
    return leaf == boundary or boundary in leaf.parents


def creation_boundary(
    target: Target, scope: str, project_path: Optional[str]
) -> Optional[Path]:
    leaf = target.leaf_dir
    if scope == SCOPE_PROJECT:
        if not project_path:
            return None
        boundary = Path(os.path.realpath(project_path))
    elif scope == SCOPE_GLOBAL and target.harness == HARNESS_CLAUDE:
        boundary = leaf.parent
    elif scope == SCOPE_GLOBAL and target.harness == HARNESS_MOD:
        boundary = leaf.parent
    elif scope == SCOPE_GLOBAL and target.harness == HARNESS_CODEX:
        boundary = leaf.parent
        if not os.path.lexists(boundary) and boundary.name == AGENTS_DIR_NAME:
            boundary = boundary.parent
    else:
        return None
    if os.path.islink(boundary) or not os.path.isdir(boundary):
        return None
    return boundary if _under(leaf, boundary) and leaf != boundary else None


def create_leaf_root(leaf: Path, boundary: Path) -> bool:
    real_boundary = Path(os.path.realpath(boundary))
    segments: List[Path] = []
    node = leaf
    while node != boundary and _under(node, boundary):
        segments.append(node)
        node = node.parent
    if node != boundary:
        raise RootCreateRefused(
            SKILL_ROOT_UNSAFE, f"{leaf} does not sit below {boundary}"
        )
    for segment in segments:
        if os.path.lexists(segment) and segment.is_symlink():
            raise RootCreateRefused(
                SKILL_ROOT_UNSAFE,
                f"{segment} is a symlink; refusing to create a skill root through it",
            )
    if not _under(Path(os.path.realpath(leaf)), real_boundary):
        raise RootCreateRefused(
            SKILL_ROOT_UNSAFE, f"{leaf} resolves outside {boundary}"
        )
    made = False
    for segment in reversed(segments):
        if os.path.isdir(segment):
            continue
        assert_test_write_allowed(segment)
        try:
            os.mkdir(segment, ROOT_MODE)
        except FileExistsError:
            continue
        except OSError as exc:
            raise RootCreateRefused(
                SKILL_ROOT_FAILED, f"the skill root {segment}: {exc.strerror or exc}"
            ) from None
        made = True
        logger.info("skill_root_created", root=str(segment))
    if made:
        notifier.notify(LOCAL_SKILLS)
    return made


def ensure_skill_roots(
    roots: InstallRoots, folder: str, harnesses: Optional[frozenset] = None
) -> List[str]:
    created: List[str] = []
    boundary = Path(os.path.realpath(folder))
    for target in roots.targets_for(KIND_SKILL, SCOPE_PROJECT, folder):
        if harnesses is not None and target.harness not in harnesses:
            continue
        if os.path.isdir(target.leaf_dir):
            continue
        if create_leaf_root(target.leaf_dir, boundary):
            created.append(str(target.leaf_dir))
    return created
