
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

import structlog

logger = structlog.get_logger()

MAX_NAME_BYTES = 255

ILLEGAL_NAME_CHARS = ("/", "\\", "\x00")

RESERVED_NAMES = (".", "..")

FALLBACK_PROJECTS_RELATIVE = (
    "Library/Mobile Documents/com~apple~CloudDocs/Sync/Development"
)


def fallback_projects_root() -> str:
    return os.path.join(os.path.expanduser("~"), FALLBACK_PROJECTS_RELATIVE)


@dataclass(frozen=True)
class ProjectDirectoryVerdict:

    ok: bool
    path: Optional[str]
    code: str
    message: str


def _real(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def canonical_path(path: str) -> str:
    return _real(path)


def _is_within(child: str, root: str) -> bool:
    child_parts = Path(child).parts
    root_parts = Path(root).parts
    if len(child_parts) < len(root_parts):
        return False
    return child_parts[: len(root_parts)] == root_parts


def within_roots(path: str, roots: Sequence[str]) -> bool:
    return any(_is_within(path, root) for root in roots)


def enclosing_projects(paths: Mapping[str, str]) -> Dict[str, List[str]]:
    real: Dict[str, str] = {}
    for key, path in paths.items():
        try:
            real[key] = _real(path)
        except (OSError, ValueError):
            continue
    out: Dict[str, List[str]] = {}
    for key, root in real.items():
        parents = [other for other, other_root in real.items() if other_root != root and _is_within(root, other_root)]
        if parents:
            out[key] = sorted(parents, key=lambda other: len(Path(real[other]).parts), reverse=True)
    return out


def projects_root(settings=None) -> str:
    if settings is not None:
        try:
            return _real(str(settings.get_working_dir()))
        except (OSError, AttributeError, ValueError) as exc:
            logger.warning("projects_root_settings_unreadable", error=str(exc))
    return _real(fallback_projects_root())


def allowed_roots(settings=None, extra: Optional[Sequence[str]] = None) -> List[str]:
    roots: List[str] = [projects_root(settings)]
    try:
        roots.append(_real(str(Path.home())))
    except (OSError, RuntimeError) as exc:
        logger.warning("allowed_roots_home_unresolvable", error=str(exc))
    for item in extra or ():
        if item:
            roots.append(_real(str(item)))

    unique: List[str] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def validate_project_dir_name(name: str) -> Optional[str]:
    if not isinstance(name, str) or not name.strip():
        return "a project name is required"

    trimmed = name.strip()

    for char in ILLEGAL_NAME_CHARS:
        if char in trimmed:
            shown = "a null character" if char == "\x00" else f"'{char}'"
            return f"a project name cannot contain {shown}"

    if any(ord(char) < 32 or ord(char) == 127 for char in trimmed):
        return "a project name cannot contain control characters"

    if trimmed in RESERVED_NAMES:
        return "a project name cannot be '.' or '..'"

    if trimmed.startswith("."):
        return "a project name cannot start with a dot"

    if len(trimmed.encode("utf-8")) > MAX_NAME_BYTES:
        return f"a project name cannot be longer than {MAX_NAME_BYTES} bytes"

    return None


def resolve_project_directory(
    chosen_dir: str,
    settings=None,
    extra_roots: Optional[Sequence[str]] = None,
) -> ProjectDirectoryVerdict:
    if not isinstance(chosen_dir, str) or not chosen_dir.strip():
        return ProjectDirectoryVerdict(
            ok=False,
            path=None,
            code="parent_missing",
            message="choose a folder to create the project in",
        )

    try:
        target_str = _real(chosen_dir)
    except (OSError, ValueError) as exc:
        return ProjectDirectoryVerdict(
            ok=False,
            path=None,
            code="cannot_determine",
            message=f"that folder could not be read: {exc}",
        )

    roots = allowed_roots(settings, extra_roots)
    if not any(_is_within(target_str, root) for root in roots):
        return ProjectDirectoryVerdict(
            ok=False,
            path=None,
            code="outside_allowed_roots",
            message=(
                "that folder is outside the places projects may be created. "
                "pick one inside your home folder or the projects folder."
            ),
        )

    target = Path(target_str)

    if target.exists():
        if not target.is_dir():
            return ProjectDirectoryVerdict(
                ok=False,
                path=None,
                code="exists_not_dir",
                message=f"a file already exists at {target_str}",
            )
    else:
        immediate_parent = target.parent
        if not immediate_parent.exists():
            return ProjectDirectoryVerdict(
                ok=False,
                path=None,
                code="parent_missing",
                message=f"that folder does not exist: {target_str}",
            )
        if not immediate_parent.is_dir():
            return ProjectDirectoryVerdict(
                ok=False,
                path=None,
                code="parent_not_dir",
                message=f"that path is not a folder: {immediate_parent}",
            )

    return ProjectDirectoryVerdict(
        ok=True, path=target_str, code="ok", message=f"will use {target_str}"
    )


def ensure_project_directory(verdict: ProjectDirectoryVerdict) -> ProjectDirectoryVerdict:
    if not verdict.ok or not verdict.path:
        return verdict
    try:
        Path(verdict.path).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "project_directory_create_failed", path=verdict.path, error=str(exc)
        )
        return ProjectDirectoryVerdict(
            ok=False,
            path=None,
            code="cannot_determine",
            message=f"could not create {verdict.path}: {exc}",
        )
    return verdict
