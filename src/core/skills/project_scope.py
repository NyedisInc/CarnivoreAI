
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, FrozenSet, Iterable

import structlog

from src.core.project_authority import MODE_DB, resolve_projects

logger = structlog.get_logger()

NEVER_A_PROJECT: tuple[str, ...] = ("/", "/etc", "/usr")


class ProjectPathRefused(ValueError):

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def known_project_roots(state_dir: Path) -> FrozenSet[str]:
    view = resolve_projects(state_dir)
    if view.mode != MODE_DB:
        logger.warning(
            "skill_project_list_unreadable",
            mode=view.mode,
            detail=view.detail,
        )
        raise ProjectPathRefused(
            "the project list could not be read, so no project install can "
            f"be confirmed as going to a project you chose (mode {view.mode!r})"
        )
    roots = set()
    for row in view.projects:
        for spelling in (row.get("root"), row.get("path")):
            if spelling:
                roots.add(os.path.realpath(str(spelling)))
    return frozenset(roots)


def _global_targets(roots: Any) -> tuple:
    return tuple(roots.targets_for("skill", "global", None)) + tuple(
        roots.legacy_targets_for("skill", "global", None)
    )


def collides_with_global(candidate: str, roots: Any) -> bool:
    project = _resolved_leaves(roots.targets_for("skill", "project", candidate))
    globals_ = _resolved_leaves(_global_targets(roots))
    return bool(project & globals_)


def resolve_project_path(
    project_path: str, *, roots: Any, state_dir: Path
) -> str:
    real = os.path.realpath(project_path)

    if real in {os.path.realpath(entry) for entry in NEVER_A_PROJECT}:
        raise ProjectPathRefused(f"{real!r} is a system directory, not a project")

    candidate = Path(real)
    for leaf in _resolved_leaves(_global_targets(roots)):
        if Path(leaf) == candidate or Path(leaf).is_relative_to(candidate):
            raise ProjectPathRefused(
                f"{real!r} contains a global install root, so installing "
                "into it as a project would write where a global install "
                "writes"
            )
    resolved_state = Path(os.path.realpath(state_dir))
    if resolved_state == candidate or resolved_state.is_relative_to(candidate):
        raise ProjectPathRefused(
            f"{real!r} contains this app's own state directory, which is "
            "never a project"
        )

    if not candidate.is_dir():
        raise ProjectPathRefused(
            f"{real!r} is not a directory that exists on this machine"
        )

    if collides_with_global(real, roots):
        raise ProjectPathRefused(
            f"a project install at {real!r} would compose the same directory "
            "a global install does"
        )

    if real not in known_project_roots(state_dir):
        raise ProjectPathRefused(
            f"{real!r} is not one of this launcher's projects; a project "
            "install may only target a project you have already added"
        )
    return real


def _resolved_leaves(targets: Iterable[Any]) -> FrozenSet[str]:
    return frozenset(os.path.realpath(target.leaf_dir) for target in targets)
