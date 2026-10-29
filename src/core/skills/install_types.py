
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.skills.roots import (
    ROOT_ABSENT,
    ROOT_IS_SYMLINK,
    ROOT_PARENT_IS_SYMLINK,
)


DIGEST_MISMATCH = "digest_mismatch"

SCRIPTS_NOT_SUPPORTED = "scripts_not_supported"

NAME_RESERVED = "name_reserved"

SCOPE_SHADOWED = "scope_shadowed"

NAME_TAKEN = "name_taken"

ALREADY_INSTALLED = "already_installed"

NO_HARNESS_PRESENT = "no_harness_present"

SHEET_REQUIRED = "sheet_required"

PROJECT_PATH_INVALID = "project_path_invalid"

SCOPE_NOT_SUPPORTED = "scope_not_supported"

AUTO_UPDATE_GLOBAL_ONLY = "auto_update_global_only"

CONSENT_REQUIRED = "consent_required"

STALE_REVISION = "stale_revision"

ROOT_ABSENT_CODE = ROOT_ABSENT

ROOT_IS_SYMLINK_CODE = ROOT_IS_SYMLINK

ROOT_PARENT_IS_SYMLINK_CODE = ROOT_PARENT_IS_SYMLINK

LOADOUT_MANIFEST_INVALID = "loadout_manifest_invalid"

LOADOUT_MEMBER_UNKNOWN = "loadout_member_unknown"

CHOICE_INSTALL_AS = "install_as"

CHOICE_REPLACE = "replace"

ALT_NAME_SUFFIX = "carnivore"


@dataclass(frozen=True)
class FileDelta:

    against: str
    added: int
    changed: int
    removed: int
    byte_delta: int


@dataclass(frozen=True)
class InstallChoice:

    action: str
    name: str
    delta: Optional[FileDelta]


@dataclass(frozen=True)
class InstallRefusal:

    code: str
    detail: str
    choices: tuple[InstallChoice, ...] = ()


@dataclass(frozen=True)
class PlannedTarget:

    harness: str
    directory: Path
    trash_root: Path
    displaces: Optional[Path]
    create_root_within: Optional[Path] = None


@dataclass(frozen=True)
class InstallPlan:

    item_id: str
    publisher: str
    name: str
    version: str
    kind: str
    digest: str
    body_sha: str
    staged: Path
    scope: str
    project_path: str
    targets: tuple[PlannedTarget, ...]
    replaces: bool
    exec_paths: tuple[str, ...] = ()
