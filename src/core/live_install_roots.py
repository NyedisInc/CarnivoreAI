
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import structlog

from src.core.sessions.ports import SettingsReader, Target
from src.core.skills import kinds
from src.core.theme_paths import user_themes_dir

logger = structlog.get_logger()


HARNESS_CLAUDE = "claude"
HARNESS_CODEX = "codex"

HARNESS_APP = "app"

HARNESS_CATALOG = "catalog"

HARNESS_MOD = "mod"

HARNESS_CPLUG = "cplug"

KIND_SKILL = kinds.KIND_SKILL
KIND_THEME = kinds.KIND_THEME
KIND_PLUGIN = kinds.KIND_PLUGIN
KIND_LOADOUT = kinds.KIND_LOADOUT
KIND_MOD = kinds.KIND_MOD
KIND_CPLUG = kinds.KIND_CPLUG
SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"

REQUIRED_MANIFEST = kinds.MANIFEST_FOR

SKILLS_DIR_NAME = "skills"
LOADOUTS_DIR_NAME = "loadouts"
MODS_DIR_NAME = "mods"
CPLUG_CODE_DIR_NAME = "cplug-code"
CLAUDE_DIR_NAME = ".claude"
CODEX_DIR_NAME = ".codex"
AGENTS_DIR_NAME = ".agents"
TRASH_DIR_NAME = ".carnivore-trash"
STAGING_DIR_NAME = ".staging"
PENDING_DIR_NAME = ".pending"
CODEX_HOME_ENV_VAR = "CODEX_HOME"

SYSTEM_DIR_NAME = ".system"

CLAUDE_BUNDLED_NAMES: tuple[str, ...] = ()


class LiveInstallRoots:

    def __init__(self, *, settings_reader: SettingsReader) -> None:
        self._settings_reader = settings_reader

    @staticmethod
    def _codex_home() -> Path:
        raw = os.environ.get(CODEX_HOME_ENV_VAR)
        if raw and raw.strip():
            return Path(raw).expanduser()
        return Path.home() / CODEX_DIR_NAME

    def _state_skills_dir(self) -> Path:
        return self._settings_reader.state_dir() / SKILLS_DIR_NAME

    def _state_loadouts_dir(self) -> Path:
        return self._settings_reader.state_dir() / LOADOUTS_DIR_NAME

    def _state_cplug_dir(self) -> Path:
        return self._settings_reader.state_dir() / CPLUG_CODE_DIR_NAME

    def targets_for(
        self, kind: str, scope: str, project_path: str | None
    ) -> tuple[Target, ...]:
        if not kinds.scope_supported(kind, scope):
            raise ValueError(
                f"{kind!r} does not install at {scope!r} scope; it installs "
                f"at {list(kinds.scopes_for(kind))}"
            )

        if kind == KIND_THEME:
            if project_path is not None:
                raise ValueError(
                    "a theme installs globally and takes no project_path"
                )
            return (Target(harness=HARNESS_APP, leaf_dir=user_themes_dir()),)

        if kind == KIND_LOADOUT:
            if project_path is not None:
                raise ValueError(
                    "a loadout installs globally and takes no project_path"
                )
            return (
                Target(
                    harness=HARNESS_CATALOG,
                    leaf_dir=self._state_loadouts_dir(),
                ),
            )

        if kind == KIND_CPLUG:
            if project_path is not None:
                raise ValueError(
                    "a cplug installs globally and takes no project_path"
                )
            return (
                Target(harness=HARNESS_CPLUG, leaf_dir=self._state_cplug_dir()),
            )

        if kind == KIND_MOD:
            if project_path is not None:
                raise ValueError(
                    "a mod installs globally and takes no project_path"
                )
            return (
                Target(
                    harness=HARNESS_MOD,
                    leaf_dir=Path.home() / CLAUDE_DIR_NAME / MODS_DIR_NAME,
                ),
            )

        if kind == KIND_PLUGIN:
            if scope == SCOPE_GLOBAL:
                if project_path is not None:
                    raise ValueError(
                        "global scope takes no project_path; passing one "
                        "means the caller has not decided which scope it "
                        "wants"
                    )
                return (
                    Target(
                        harness=HARNESS_CLAUDE,
                        leaf_dir=Path.home() / CLAUDE_DIR_NAME / SKILLS_DIR_NAME,
                    ),
                )
            if project_path is None or not project_path.strip():
                raise ValueError(
                    "project scope requires a project_path; an absent one "
                    "would resolve against the process working directory"
                )
            return (
                Target(
                    harness=HARNESS_CLAUDE,
                    leaf_dir=Path(os.path.realpath(project_path))
                    / CLAUDE_DIR_NAME
                    / SKILLS_DIR_NAME,
                ),
            )

        if scope == SCOPE_GLOBAL:
            if project_path is not None:
                raise ValueError(
                    "global scope takes no project_path; passing one means "
                    "the caller has not decided which scope it wants"
                )
            return (
                Target(
                    harness=HARNESS_CLAUDE,
                    leaf_dir=Path.home() / CLAUDE_DIR_NAME / SKILLS_DIR_NAME,
                ),
                Target(
                    harness=HARNESS_CODEX,
                    leaf_dir=Path.home() / AGENTS_DIR_NAME / SKILLS_DIR_NAME,
                ),
            )
        if scope == SCOPE_PROJECT:
            if project_path is None or not project_path.strip():
                raise ValueError(
                    "project scope requires a project_path; an absent one "
                    "would resolve against the process working directory"
                )
            real = Path(os.path.realpath(project_path))
            return (
                Target(
                    harness=HARNESS_CLAUDE,
                    leaf_dir=real / CLAUDE_DIR_NAME / SKILLS_DIR_NAME,
                ),
                Target(
                    harness=HARNESS_CODEX,
                    leaf_dir=real / AGENTS_DIR_NAME / SKILLS_DIR_NAME,
                ),
            )
        raise ValueError(
            f"unknown install scope {scope!r}; known scopes are "
            f"{sorted((SCOPE_GLOBAL, SCOPE_PROJECT))}"
        )

    def legacy_targets_for(
        self, kind: str, scope: str, project_path: str | None
    ) -> tuple[Target, ...]:
        if kind == KIND_SKILL and scope == SCOPE_GLOBAL and project_path is None:
            return (
                Target(
                    harness=HARNESS_CODEX,
                    leaf_dir=self._codex_home() / SKILLS_DIR_NAME,
                ),
            )
        return ()

    def present_harnesses(self) -> tuple[str, ...]:
        present: list[str] = []
        if os.path.isdir(Path.home() / CLAUDE_DIR_NAME):
            present.append(HARNESS_CLAUDE)
        if os.path.isdir(self._codex_home()) or os.path.isdir(
            Path.home() / AGENTS_DIR_NAME
        ):
            present.append(HARNESS_CODEX)
        if os.path.isdir(Path.home() / CLAUDE_DIR_NAME / MODS_DIR_NAME):
            present.append(HARNESS_MOD)
        return tuple(present)

    def required_manifest(self, kind: str) -> str:
        return kinds.manifest_name(kind)

    def trash_dir(
        self, harness: str, scope: str, project_path: str | None
    ) -> Path:
        for target in self._targets_at(scope, project_path):
            if target.harness == harness:
                return target.leaf_dir.parent / TRASH_DIR_NAME
        raise ValueError(
            f"unknown harness {harness!r} at {scope!r} scope; known "
            f"harnesses are {sorted(self._harnesses_at(scope, project_path))}"
        )

    def _targets_at(
        self, scope: str, project_path: str | None
    ) -> Iterator[Target]:
        for kind in kinds.KINDS:
            if not kinds.scope_supported(kind, scope):
                continue
            yield from self.targets_for(kind, scope, project_path)

    def _harnesses_at(
        self, scope: str, project_path: str | None
    ) -> tuple[str, ...]:
        return tuple(
            sorted({target.harness for target in self._targets_at(scope, project_path)})
        )

    def staging_dir(self) -> Path:
        return self._state_skills_dir() / STAGING_DIR_NAME

    def pending_dir(self) -> Path:
        return self._state_skills_dir() / PENDING_DIR_NAME

    def root_listing(self, harness: str) -> tuple[str, ...]:
        for target in self._targets_at(SCOPE_GLOBAL, None):
            if target.harness == harness:
                try:
                    with os.scandir(target.leaf_dir) as entries:
                        return tuple(sorted(entry.name for entry in entries))
                except OSError as exc:
                    logger.debug(
                        "install_root_listing_unreadable",
                        harness=harness,
                        root=str(target.leaf_dir),
                        error=str(exc),
                    )
                    return ()
        raise ValueError(
            f"unknown harness {harness!r}; known harnesses are "
            f"{sorted(self._harnesses_at(SCOPE_GLOBAL, None))}"
        )

    def _read_only_roots(self, harness: str) -> tuple[Path, ...]:
        if harness == HARNESS_CLAUDE:
            return ()
        if harness == HARNESS_CODEX:
            return (
                self._codex_home() / SKILLS_DIR_NAME,
                self._codex_home() / SKILLS_DIR_NAME / SYSTEM_DIR_NAME,
            )
        raise ValueError(
            f"unknown harness {harness!r}; known harnesses are "
            f"{sorted((HARNESS_CLAUDE, HARNESS_CODEX))}"
        )

    def read_only_listing(self, harness: str) -> tuple[str, ...]:
        if harness == HARNESS_CLAUDE:
            return CLAUDE_BUNDLED_NAMES

        names: set[str] = set()
        for root in self._read_only_roots(harness):
            if not os.path.lexists(root):
                continue
            if os.path.islink(root):
                logger.debug(
                    "install_read_only_root_is_link",
                    harness=harness,
                    root=str(root),
                )
                continue
            try:
                with os.scandir(root) as entries:
                    names.update(entry.name for entry in entries)
            except OSError as exc:
                logger.debug(
                    "install_read_only_root_unreadable",
                    harness=harness,
                    root=str(root),
                    error=str(exc),
                )
        return tuple(sorted(names))

