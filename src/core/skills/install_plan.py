
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional, Union

import structlog

from src.core.catalog.verify import check_digest, check_scripts
from src.core.sessions.ports import InstallRoots, Target
from src.core.skills.digest import hash_file
from src.core.skills.install_collision import (
    compute_delta,
    is_managed_by,
    listing_collision,
)
from src.core.skills.install_types import (
    ALREADY_INSTALLED,
    ALT_NAME_SUFFIX,
    CHOICE_INSTALL_AS,
    CHOICE_REPLACE,
    DIGEST_MISMATCH,
    NAME_RESERVED,
    NAME_TAKEN,
    NO_HARNESS_PRESENT,
    ROOT_ABSENT_CODE,
    ROOT_IS_SYMLINK_CODE,
    ROOT_PARENT_IS_SYMLINK_CODE,
    SCOPE_SHADOWED,
    SCRIPTS_NOT_SUPPORTED,
    FileDelta,
    InstallChoice,
    InstallPlan,
    InstallRefusal,
    PlannedTarget,
)
from src.core.skills.ledger import (
    GLOBAL_PROJECT_PATH,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    InstallLedger,
)
from src.core.skills.kinds import manifest_name
from src.core.skill_manager.root_create import creation_boundary
from src.core.live_install_roots import HARNESS_CLAUDE, HARNESS_CODEX
from src.core.skills.roots import (
    ROOT_ABSENT,
    ROOT_IS_SYMLINK,
    ROOT_PARENT_IS_SYMLINK,
    TARGET_EXISTS,
    TARGET_IS_SYMLINK,
    check_root,
    target_dir,
    unsafe_name_reason,
)
from src.core.skills.stage import StagedSkill, executable_members
from src.models.catalog import CatalogItem, ItemVersion

logger = structlog.get_logger()


def is_reserved_name(name: str) -> Optional[str]:
    return unsafe_name_reason(name)


def alternative_name(name: str) -> str:
    return f"{name}-{ALT_NAME_SUFFIX}"



def _canonical_project_path(scope: str, project_path: Optional[str]) -> str:
    if scope == SCOPE_GLOBAL:
        return GLOBAL_PROJECT_PATH
    if scope == SCOPE_PROJECT:
        if project_path is None or not project_path.strip():
            raise ValueError(
                "project scope requires a project_path; an absent one would "
                "resolve against the process working directory"
            )
        return os.path.realpath(project_path)
    raise ValueError(
        f"unknown install scope {scope!r}; known scopes are "
        f"{sorted((SCOPE_GLOBAL, SCOPE_PROJECT))}"
    )


def _shadow_refusal(
    ledger: InstallLedger, name: str, scope: str, project_path: str
) -> Optional[InstallRefusal]:
    rows = ledger.find_name_any_scope(name)
    if scope == SCOPE_PROJECT:
        global_rows = [row for row in rows if row.scope == SCOPE_GLOBAL]
        if global_rows:
            return InstallRefusal(
                code=SCOPE_SHADOWED,
                detail=(
                    f"{name!r} is already installed globally as "
                    f"{global_rows[0].item_id!r}; Claude prefers the personal "
                    "(global) copy over the project one, so a project copy "
                    "would be ignored; uninstall the global copy first"
                ),
            )
        return None

    project_rows = [
        row
        for row in rows
        if row.scope == SCOPE_PROJECT and row.project_path != project_path
    ]
    if project_rows:
        places = ", ".join(sorted(row.project_path for row in project_rows))
        return InstallRefusal(
            code=SCOPE_SHADOWED,
            detail=(
                f"{name!r} is already installed in {len(project_rows)} "
                f"project(s): {places}. A global copy would take precedence "
                "over them there, so uninstall those first or install under another "
                "name"
            ),
        )
    return None


def _root_refusal(check_state: str, target: Target, root: Path) -> InstallRefusal:
    if check_state == ROOT_ABSENT:
        return InstallRefusal(
            code=ROOT_ABSENT_CODE,
            detail=(
                f"the {target.harness} skills root {root} is not there. Ask "
                "for the install with create_roots to have this app make that "
                "one skills folder (it never makes a harness's own home)"
            ),
        )
    if check_state == ROOT_PARENT_IS_SYMLINK:
        return InstallRefusal(
            code=ROOT_PARENT_IS_SYMLINK_CODE,
            detail=(
                f"the directory above the {target.harness} skills root "
                f"{root} is a symlink, so the root reads cleanly while "
                "being somewhere the user did not name"
            ),
        )
    return InstallRefusal(
        code=ROOT_IS_SYMLINK_CODE,
        detail=(
            f"the {target.harness} skills root {root} is a symlink, so a "
            "write into it would land somewhere the user did not name"
        ),
    )



def plan_install(
    *,
    item: CatalogItem,
    version: ItemVersion,
    staged: StagedSkill,
    scope: str,
    project_path: Optional[str],
    ledger: InstallLedger,
    roots: InstallRoots,
    discovery_listing: Iterable[str],
    choice: Optional[str] = None,
    allow_scripts: bool = False,
    harnesses: Optional[frozenset] = None,
    create_roots: bool = False,
) -> Union[InstallPlan, InstallRefusal]:
    canonical_project = _canonical_project_path(scope, project_path)

    digest_refusal = check_digest(version.digest, staged.digest)
    if digest_refusal is not None:
        return InstallRefusal(
            code=DIGEST_MISMATCH, detail=digest_refusal.detail
        )

    if not allow_scripts:
        scripts_refusal = check_scripts(version)
        if scripts_refusal is not None:
            return InstallRefusal(
                code=SCRIPTS_NOT_SUPPORTED, detail=scripts_refusal.detail
            )
        if staged.archive.script_members:
            return InstallRefusal(
                code=SCRIPTS_NOT_SUPPORTED,
                detail=(
                    f"the staged copy of {item.id!r} carries "
                    f"{len(staged.archive.script_members)} executable member(s) "
                    "while the index declares none; installing it needs a "
                    "consent naming these bytes"
                ),
            )

    folder_name = (
        alternative_name(item.name) if choice == CHOICE_INSTALL_AS else item.name
    )
    reserved = is_reserved_name(folder_name)
    if reserved is not None:
        return InstallRefusal(code=NAME_RESERVED, detail=reserved)

    shadowed = _shadow_refusal(ledger, folder_name, scope, canonical_project)
    if shadowed is not None:
        return shadowed

    if ledger.find(item.id, scope, canonical_project) is not None:
        return InstallRefusal(
            code=ALREADY_INSTALLED,
            detail=(
                f"{item.id!r} is already installed at {scope} scope; "
                "changing the version installed is an update, not an install"
            ),
        )
    owner = ledger.find_by_name(folder_name, scope, canonical_project)
    if owner is not None:
        return InstallRefusal(
            code=ALREADY_INSTALLED,
            detail=(
                f"the folder name {folder_name!r} at {scope} scope belongs "
                f"to {owner.item_id!r}, which this app installed; uninstall "
                "it or install under another name"
            ),
        )

    roots_project = None if scope == SCOPE_GLOBAL else project_path
    targets = roots.targets_for(item.kind, scope, roots_project)
    if harnesses is not None:
        wanted = tuple(
            t
            for t in targets
            if t.harness not in (HARNESS_CLAUDE, HARNESS_CODEX)
            or t.harness in harnesses
        )
        if not wanted:
            return InstallRefusal(
                code=NO_HARNESS_PRESENT,
                detail=(
                    f"no agent this install writes for is present on this "
                    f"machine (looked for {sorted(t.harness for t in targets)}, "
                    f"present {sorted(harnesses)})"
                ),
            )
        targets = wanted
    planned: list[PlannedTarget] = []
    occupied: list[Path] = []
    for target in targets:
        state = check_root(target, folder_name).state
        if state == ROOT_ABSENT and create_roots:
            boundary = creation_boundary(target, scope, roots_project)
            if boundary is not None:
                planned.append(
                    PlannedTarget(
                        harness=target.harness,
                        directory=target_dir(target, folder_name),
                        trash_root=roots.trash_dir(
                            target.harness, scope, roots_project
                        ),
                        displaces=None,
                        create_root_within=boundary,
                    )
                )
                continue
        if state in (ROOT_ABSENT, ROOT_IS_SYMLINK, ROOT_PARENT_IS_SYMLINK):
            return _root_refusal(state, target, target.leaf_dir)
        directory = target_dir(target, folder_name)
        if state == TARGET_IS_SYMLINK:
            return InstallRefusal(
                code=NAME_TAKEN,
                detail=(
                    f"{directory} is a symlink. This app does not replace a "
                    "link it did not create, because what it points at is "
                    "not in this directory at all"
                ),
                choices=_choices(folder_name, item.name, None, replace_ok=False),
            )
        displaces: Optional[Path] = None
        if state == TARGET_EXISTS:
            occupied.append(directory)
            displaces = directory
        planned.append(
            PlannedTarget(
                harness=target.harness,
                directory=directory,
                trash_root=roots.trash_dir(
                    target.harness, scope, roots_project
                ),
                displaces=displaces,
            )
        )

    listing_hit = listing_collision(folder_name, discovery_listing)
    if listing_hit is not None:
        return InstallRefusal(
            code=NAME_TAKEN,
            detail=(
                f"{folder_name!r} is already a skill in a root this app "
                "reads but never writes, so a copy of that name would be "
                "listed twice and this app could not replace the other one"
            ),
            choices=_choices(folder_name, item.name, None, replace_ok=False),
        )

    if occupied and choice != CHOICE_REPLACE:
        delta = compute_delta(occupied[0], staged.path)
        return InstallRefusal(
            code=NAME_TAKEN,
            detail=(
                f"{folder_name!r} is already a folder this app did not "
                f"install: {', '.join(str(path) for path in occupied)}"
            ),
            choices=_choices(folder_name, item.name, delta, replace_ok=True),
        )

    if occupied and choice == CHOICE_REPLACE:
        for directory in occupied:
            if is_managed_by(directory, item.id):
                return InstallRefusal(
                    code=ALREADY_INSTALLED,
                    detail=(
                        f"{directory} already holds {item.id!r}; replacing "
                        "this app's own install is an update, not an install"
                    ),
                )

    body_sha, _size = hash_file(staged.path / manifest_name(item.kind))
    plan = InstallPlan(
        item_id=item.id,
        publisher=item.publisher,
        name=folder_name,
        version=version.v,
        kind=item.kind,
        digest=staged.digest,
        body_sha=body_sha,
        staged=staged.path,
        scope=scope,
        project_path=canonical_project,
        targets=tuple(planned),
        replaces=bool(occupied),
        exec_paths=executable_members(staged.archive) if allow_scripts else (),
    )
    logger.info(
        "skill_install_planned",
        item_id=plan.item_id,
        name=plan.name,
        scope=plan.scope,
        targets=len(plan.targets),
        replaces=plan.replaces,
        scripts=len(plan.exec_paths),
    )
    return plan


def _choices(
    folder_name: str,
    item_name: str,
    delta: Optional[FileDelta],
    *,
    replace_ok: bool,
) -> tuple[InstallChoice, ...]:
    choices: list[InstallChoice] = []
    if folder_name == item_name:
        choices.append(
            InstallChoice(
                action=CHOICE_INSTALL_AS,
                name=alternative_name(item_name),
                delta=None,
            )
        )
    if replace_ok:
        choices.append(
            InstallChoice(action=CHOICE_REPLACE, name=folder_name, delta=delta)
        )
    return tuple(choices)
