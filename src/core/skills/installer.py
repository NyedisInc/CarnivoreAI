"""Perform an install plan, and manage the staging area it is built in.

:mod:`src.core.skills.install_plan` decided. This acts, and it makes no
decisions of its own: every path it writes to was composed by the planner
through :func:`src.core.skills.roots.target_dir`, and every filesystem
operation goes through :mod:`src.core.skills.targets`, which is where the
write guard lives.

**THE SIDECAR IS WRITTEN INTO THE STAGED COPY, BEFORE THE FIRST TARGET.**
Writing it into each installed folder afterwards would mean two folders
that are supposed to be identical passing through a window where they are
not, and a crash inside that window leaves one harness with provenance and
the other without. Writing it once, into the source of every copy, makes
the two copies identical by construction.

**IT IS WRITTEN AFTER THE DIGEST WAS CHECKED, AND THAT IS ON PURPOSE.**
The sidecar is this app's own file; it is not part of what the publisher
signed, so adding it changes the folder's digest. The digest is verified
against the signature BEFORE this function runs (the planner does it), and
what is recorded in the ledger is the digest of the SIGNED bytes, not of
the folder with the sidecar in it. Recomputing it afterwards would record
a number that matches no signature anywhere.

**A FAILURE AFTER THE FIRST COPY REMOVES WHAT THIS CALL WROTE.** Half an
install is worse than none: a skill folder in one harness root is a skill
that harness loads, and there would be no ledger row saying it is there.
So every directory this call created is removed and the original error is
re-raised.

**WHAT IS NOT PUT BACK IS A FOLDER THIS CALL DISPLACED.** When the user
chose ``replace``, their folder was renamed into that harness's trash
before the copy. If a later target fails, the displaced folder STAYS in
the trash and its path is logged at WARNING. Moving it back would need a
rename this module is not allowed to perform (every rename lives in
``targets.py``, and the only one it exposes for this shape is half of a
swap). The trash is kept for a fortnight by
:class:`src.core.skills.sweeper.SkillSweeper`, the folder is intact, and
the log line names exactly where it is. An interrupted UPDATE is the case
that gets the full journal treatment, in
:mod:`src.core.skills.updates`.

**THE STAGING CAP IS A REFUSAL, NOT A QUEUE.** A bounded staging area with
no bound on how long a caller may hold one is a disk that fills. The cap
and the reaper are one decision, which is why the number lives in the
sweeper module.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.core.sessions.ports import Clock, InstallRoots
from src.core.skill_manager.root_create import RootCreateRefused, create_leaf_root
from src.core.skills.consent_via_ddl import CONSENT_VIA_VALUES
from src.core.skills.install_types import InstallPlan
from src.core.skills.ledger import InstallLedger, InstallTarget, InstalledItem
from src.core.skills.records import SkillRecord, write_sidecar
from src.core.skills.sweeper import MAX_CONCURRENT_STAGING
from src.core.skills.targets import copy_tree, move_to_trash, remove_tree
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

STAGING_BUSY = "staging_busy"

STAGING_MODE = 0o700


class StagingBusy(RuntimeError):

    code = STAGING_BUSY

    def __init__(self, detail: str, in_use: int, cap: int) -> None:
        super().__init__(detail)
        self.in_use = in_use
        self.cap = cap


def iso_from(clock: Clock) -> str:
    moment = datetime.fromtimestamp(clock.now(), tz=timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def trash_stamp(clock: Clock) -> str:
    """A compact uniquifier for a displaced folder's name.

    Description: ``move_to_trash`` joins this to a directory name and
      refuses a separator in it, so the format deliberately carries none:
      ``20260915T120000Z``. Second resolution is enough because the mover
      refuses a destination that already exists rather than overwriting
      one, so a collision is a loud failure and never a lost folder.
    Inputs: clock (Clock).
    Output: str.
    Example: trash_stamp(SystemClock())  # '20260915T120000Z'
    """
    moment = datetime.fromtimestamp(clock.now(), tz=timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def staging_root_for(roots: InstallRoots) -> Path:
    staging = roots.staging_dir()
    assert_test_write_allowed(staging)
    staging.mkdir(parents=True, exist_ok=True)
    os.chmod(staging, STAGING_MODE)

    try:
        with os.scandir(staging) as entries:
            in_use = sum(1 for _entry in entries)
    except OSError as exc:
        raise StagingBusy(
            f"the staging area {staging} could not be read: {exc}",
            in_use=MAX_CONCURRENT_STAGING,
            cap=MAX_CONCURRENT_STAGING,
        ) from exc

    if in_use >= MAX_CONCURRENT_STAGING:
        logger.warning(
            "skill_staging_busy", in_use=in_use, cap=MAX_CONCURRENT_STAGING
        )
        raise StagingBusy(
            f"{in_use} staging directories are already open, which is the "
            f"cap of {MAX_CONCURRENT_STAGING}",
            in_use=in_use,
            cap=MAX_CONCURRENT_STAGING,
        )

    directory = staging / uuid.uuid4().hex
    assert_test_write_allowed(directory)
    directory.mkdir(mode=STAGING_MODE)
    os.chmod(directory, STAGING_MODE)
    logger.debug("skill_staging_opened", path=str(directory), in_use=in_use + 1)
    return directory


def discard_staging(path: Path) -> None:
    remove_tree(path)
    logger.debug("skill_staging_discarded", path=str(path))


def apply_install(
    plan: InstallPlan,
    *,
    ledger: InstallLedger,
    roots: InstallRoots,
    clock: Clock,
    source_index_url: str,
    publisher_key_id: str,
    consent_via: str,
) -> InstalledItem:
    manifest = roots.required_manifest(plan.kind)
    if not (plan.staged / manifest).is_file():
        raise FileNotFoundError(
            f"{plan.staged} carries no {manifest}; a folder without it is "
            "not something either harness would load"
        )

    stamp = iso_from(clock)
    written: list[Path] = []
    displaced: list[Path] = []
    made_roots: list[Path] = []

    record = SkillRecord(
        publisher=plan.publisher,
        name=plan.name,
        version=plan.version,
        digest=plan.digest,
        source_index_url=source_index_url,
        installed_at=stamp,
    )
    write_sidecar(plan.staged, record)

    if consent_via not in CONSENT_VIA_VALUES:
        raise ValueError(f"unknown consent_via {consent_via!r}")

    try:
        for target in plan.targets:
            if target.create_root_within is not None:
                try:
                    if create_leaf_root(
                        target.directory.parent, target.create_root_within
                    ):
                        made_roots.append(target.directory.parent)
                except RootCreateRefused as exc:
                    raise OSError(exc.detail) from exc
            if target.displaces is not None:
                displaced.append(
                    move_to_trash(
                        target.displaces, target.trash_root, trash_stamp(clock)
                    )
                )
            copy_tree(
                plan.staged,
                target.directory,
                exec_paths=frozenset(plan.exec_paths),
            )
            written.append(target.directory)

        install_id = uuid.uuid4().hex
        stored = ledger.insert(
            InstalledItem(
                install_id=install_id,
                item_id=plan.item_id,
                kind=plan.kind,
                publisher=plan.publisher,
                name=plan.name,
                version=plan.version,
                digest=plan.digest,
                scope=plan.scope,
                project_path=plan.project_path,
                auto_update=False,
                source_index_url=source_index_url,
                consented_digest=plan.digest,
                consented_body_sha=plan.body_sha,
                publisher_key_id=publisher_key_id,
                revision=1,
                installed_at=stamp,
                updated_at=stamp,
                consent_via=consent_via,
            ),
            [
                InstallTarget(
                    install_id=install_id,
                    harness=target.harness,
                    path=str(target.directory),
                )
                for target in plan.targets
            ],
        )
    except BaseException:
        _undo(written, displaced, made_roots)
        raise

    logger.info(
        "skill_installed",
        install_id=stored.install_id,
        item_id=stored.item_id,
        name=stored.name,
        scope=stored.scope,
        version=stored.version,
        targets=len(plan.targets),
        replaced=len(displaced),
    )
    return stored


def _undo(
    written: list[Path], displaced: list[Path], made_roots: list[Path]
) -> None:
    for directory in written:
        try:
            remove_tree(directory)
        except OSError as exc:
            logger.warning(
                "skill_install_rollback_failed",
                path=str(directory),
                error=str(exc),
            )
    for root in made_roots:
        try:
            assert_test_write_allowed(root)
            root.rmdir()
        except OSError:
            pass
    for path in displaced:
        logger.warning(
            "skill_install_left_displaced_copy",
            path=str(path),
            detail=(
                "the install failed after this folder was moved out of the "
                "way; it is intact at this path and the sweeper keeps it "
                "for a fortnight"
            ),
        )
