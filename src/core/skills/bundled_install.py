
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.core.live_install_roots import HARNESS_CLAUDE, HARNESS_CODEX
from src.core.skill_manager.root_create import RootCreateRefused, create_leaf_root, creation_boundary
from src.core.skill_watch.measure import TooLarge
from src.core.skill_watch.sentinel import measure_folder
from src.core.skills.digest import digest_directory, hash_file
from src.core.skills.installer import discard_staging, iso_from, staging_root_for, trash_stamp
from src.core.skills.kinds import KIND_SKILL, manifest_name
from src.core.skills.ledger import InstallLedger, InstallTarget, InstalledItem
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL
from src.core.skills.records import SkillRecord, write_sidecar
from src.core.skills.roots import ROOT_ABSENT, ROOT_OK, TARGET_EXISTS, check_root, target_dir
from src.core.skills.targets import copy_tree, move_to_trash, remove_tree, swap_in

logger = structlog.get_logger()

BUNDLED_ROOT = Path(__file__).resolve().parent / "bundled"

BUNDLED_SOURCE = "bundled"

MANIFEST = manifest_name(KIND_SKILL)

CONSENT = "one_click"

OUTCOME_INSTALLED = "installed"
OUTCOME_ADOPTED = "adopted"
OUTCOME_UPDATED = "updated"
OUTCOME_CURRENT = "current"
OUTCOME_LOCAL_EDITS = "local_edits"
OUTCOME_BLOCKED = "blocked"
OUTCOME_MISSING = "missing"
OUTCOME_WITHDRAWN = "withdrawn"


class BundledSkillError(RuntimeError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class BundledCopy:

    harness: str
    directory: Path
    create_within: Optional[Path]
    adopt: bool


def bundled_dir(folder: str) -> Path:
    path = BUNDLED_ROOT / folder
    if not (path / MANIFEST).is_file():
        raise BundledSkillError("bundled_missing", f"the app carries no bundled skill {folder!r}")
    return path


def bundled_digest(folder: str) -> str:
    return digest_directory(bundled_dir(folder))[0]


def bundled_version(digest: str) -> str:
    return f"bundled-{digest[:8]}"


def plan_copies(services, name: str, digest: str) -> List[BundledCopy]:
    roots = services.install_roots
    present = frozenset(roots.present_harnesses())
    copies: List[BundledCopy] = []
    for target in roots.targets_for("skill", SCOPE_GLOBAL, None):
        if target.harness in (HARNESS_CLAUDE, HARNESS_CODEX) and target.harness not in present:
            continue
        state = check_root(target, name).state
        directory = target_dir(target, name)
        if state == ROOT_OK:
            copies.append(BundledCopy(target.harness, directory, None, False))
        elif state == ROOT_ABSENT:
            boundary = creation_boundary(target, SCOPE_GLOBAL, None)
            if boundary is not None:
                copies.append(BundledCopy(target.harness, directory, boundary, False))
            else:
                logger.info("skills_bundled_root_skipped", harness=target.harness, state=state)
        elif state == TARGET_EXISTS and _folder_digest(directory) == digest:
            copies.append(BundledCopy(target.harness, directory, None, True))
        else:
            logger.info("skills_bundled_copy_skipped", harness=target.harness, state=state, folder=str(directory))
    return copies


def _folder_digest(folder: Path) -> Optional[str]:
    try:
        return measure_folder(folder)[0]
    except (OSError, TooLarge) as exc:
        logger.warning("skills_bundled_unmeasurable", folder=str(folder), error=type(exc).__name__)
        return None


def install_bundled(services, item_id: str, folder: str) -> Tuple[str, InstalledItem]:
    publisher, name = item_id.split("/", 1)
    source = bundled_dir(folder)
    digest = digest_directory(source)[0]
    version = bundled_version(digest)
    with services.catalog.ledger() as ledger:
        if ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) is not None:
            raise BundledSkillError("already_installed", f"{item_id!r} is already installed")
        owner = ledger.find_by_name(name, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
        if owner is not None:
            raise BundledSkillError("name_taken", f"the folder name {name!r} belongs to {owner.item_id!r}")
        copies = plan_copies(services, name, digest)
        if not copies:
            raise BundledSkillError("blocked", f"a folder named {name!r} that is not this app's is in the way, or no agent is present")
        stamp = iso_from(services.clock)
        record = SkillRecord(publisher=publisher, name=name, version=version, digest=digest,
                             source_index_url=BUNDLED_SOURCE, installed_at=stamp)
        staging = staging_root_for(services.install_roots)
        written: List[Path] = []
        try:
            staged = staging / name
            copy_tree(source, staged)
            write_sidecar(staged, record)
            for copy in copies:
                if copy.adopt:
                    write_sidecar(copy.directory, record)
                    continue
                if copy.create_within is not None:
                    try:
                        create_leaf_root(copy.directory.parent, copy.create_within)
                    except RootCreateRefused as exc:
                        raise OSError(exc.detail) from exc
                copy_tree(staged, copy.directory)
                written.append(copy.directory)
            install_id = uuid.uuid4().hex
            row = ledger.insert(
                InstalledItem(
                    install_id=install_id, item_id=item_id, kind="skill", publisher=publisher, name=name,
                    version=version, digest=digest, scope=SCOPE_GLOBAL, project_path=GLOBAL_PROJECT_PATH,
                    auto_update=False, source_index_url=BUNDLED_SOURCE, consented_digest=digest,
                    consented_body_sha=hash_file(source / MANIFEST)[0], publisher_key_id=BUNDLED_SOURCE,
                    revision=1, installed_at=stamp, updated_at=stamp, consent_via=CONSENT),
                [InstallTarget(install_id=install_id, harness=c.harness, path=str(c.directory)) for c in copies])
        except BaseException:
            for directory in written:
                remove_tree(directory)
            raise
        finally:
            discard_staging(staging)
    outcome = OUTCOME_ADOPTED if all(c.adopt for c in copies) else OUTCOME_INSTALLED
    logger.info("skills_bundled_installed", item_id=item_id, outcome=outcome, harnesses=[c.harness for c in copies])
    return outcome, row


def local_edits(services, row: InstalledItem) -> bool:
    with services.catalog.ledger() as ledger:
        targets = ledger.targets(row.install_id)
    for target in targets:
        folder = Path(target.path)
        if os.path.lexists(folder) and _folder_digest(folder) != row.digest:
            return True
    return False


def refresh_bundled(services, row: InstalledItem, folder: str) -> str:
    source = bundled_dir(folder)
    digest = digest_directory(source)[0]
    if row.digest == digest and not local_edits(services, row):
        return OUTCOME_CURRENT
    with services.catalog.ledger() as ledger:
        targets = ledger.targets(row.install_id)
        folders = [(t.harness, Path(t.path)) for t in targets]
        if any(not os.path.lexists(path) for _h, path in folders):
            return OUTCOME_MISSING
        if any(_folder_digest(path) != row.digest for _h, path in folders):
            return OUTCOME_LOCAL_EDITS
        if row.digest == digest:
            return OUTCOME_CURRENT
        stamp = iso_from(services.clock)
        version = bundled_version(digest)
        record = SkillRecord(publisher=row.publisher, name=row.name, version=version, digest=digest,
                             source_index_url=BUNDLED_SOURCE, installed_at=stamp)
        staged: List[Tuple[str, Path, Path]] = []
        try:
            for harness, path in folders:
                sibling = path.parent / f".{path.name}.new-{uuid.uuid4().hex[:8]}"
                staged.append((harness, path, sibling))
                copy_tree(source, sibling)
                write_sidecar(sibling, record)
            for harness, path, sibling in staged:
                swap_in(sibling, path, trash_root=services.install_roots.trash_dir(harness, SCOPE_GLOBAL, None),
                        stamp=trash_stamp(services.clock))
        except BaseException:
            for _harness, _path, sibling in staged:
                if os.path.lexists(sibling):
                    remove_tree(sibling)
            raise
        ledger.update(row.install_id, expected_revision=row.revision, now=stamp, version=version, digest=digest,
                      consented_digest=digest, consented_body_sha=hash_file(source / MANIFEST)[0])
    logger.info("skills_bundled_updated", item_id=row.item_id, digest=digest[:12])
    return OUTCOME_UPDATED


def withdraw_bundled(services, row: InstalledItem) -> str:
    with services.catalog.ledger() as ledger:
        targets = ledger.targets(row.install_id)
        folders = [(t.harness, Path(t.path)) for t in targets]
        if any(os.path.lexists(path) and _folder_digest(path) != row.digest for _h, path in folders):
            logger.info("skills_bundled_withdraw_kept_edited", item_id=row.item_id)
            return OUTCOME_LOCAL_EDITS
        stamp = trash_stamp(services.clock)
        moved = [str(move_to_trash(path, services.install_roots.trash_dir(harness, SCOPE_GLOBAL, None), stamp))
                 for harness, path in folders if os.path.lexists(path)]
        ledger.delete(row.install_id)
    logger.info("skills_bundled_withdrawn", item_id=row.item_id, trashed=len(moved))
    return OUTCOME_WITHDRAWN
