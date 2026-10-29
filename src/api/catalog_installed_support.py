
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional, Tuple

import structlog
from fastapi import HTTPException, Request

from src.api import catalog_mod_gates
from src.api.catalog_install_support import announce_theme_change, refuse_409
from src.api.catalog_theme_rules import drop_theme_run_grant_with, prune_theme_pins_with
from src.core.sessions.ports import InstallRoots
from src.cplugs.host.adoption import BUILTIN_SOURCE
from src.core.skill_watch.store import default_watch_store
from src.core.skills.required import mark_declined
from src.core.skills.legacy_trash import trash_root_for
from src.core.skills.kinds import KIND_CPLUG, KIND_MOD
from src.core.skills.install_types import (
    AUTO_UPDATE_GLOBAL_ONLY,
    STALE_REVISION,
)
from src.core.skills.installer import iso_from, trash_stamp
from src.core.skills.ledger_types import (
    SCOPE_GLOBAL,
    InstalledItem,
    InstallNotFound,
    InstallTarget,
    StaleRevision,
    as_dict,
)
from src.core.skills.records import SkillRecord, write_sidecar
from src.core.skills.stage import executable_members
from src.core.skills.targets import copy_tree, move_to_trash
from src.core.skills.update_journal import (
    STEP_WRITTEN,
    PendingJournal,
    apply_swap,
    pending_path,
    write_pending,
)
from src.models.catalog import ItemVersion
from src.models.catalog_api import InstalledPatchRequest, UninstallResponse

logger = structlog.get_logger()

INCOMING_SUFFIX = "-carnivore-incoming-"


def stale_409(current: InstalledItem) -> HTTPException:
    return refuse_409(
        STALE_REVISION,
        f"install {current.install_id!r} is at revision {current.revision}",
        current=as_dict(current),
    )


def not_found_404(install_id: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=f"no install carries the id {install_id!r}"
    )


def refuse_builtin(row: InstalledItem) -> None:
    if row.source_index_url == BUILTIN_SOURCE:
        raise refuse_409(
            "builtin_cplug",
            f"{row.item_id!r} ships inside this app; it cannot be updated, uninstalled or changed from the catalog",
        )


def row_now(request: Request, install_id: str) -> InstalledItem:
    with request.app.state.services.catalog.ledger() as ledger:
        row = ledger.get(install_id)
    if row is None:
        raise not_found_404(install_id)
    return row


def project_of(row: InstalledItem) -> Optional[str]:
    return None if row.scope == SCOPE_GLOBAL else row.project_path


def trash_targets(
    row: InstalledItem,
    targets: Tuple[InstallTarget, ...],
    *,
    roots: InstallRoots,
    stamp: str,
) -> Tuple[List[str], List[str]]:
    project = project_of(row)
    trashed: List[str] = []
    missing: List[str] = []
    for target in targets:
        path = Path(target.path)
        if not os.path.lexists(path):
            missing.append(str(path))
            continue
        trash_root = trash_root_for(
            roots, kind=row.kind, harness=target.harness, scope=row.scope,
            project_path=project, live_path=path,
        )
        trashed.append(str(move_to_trash(path, trash_root, stamp)))
    return trashed, missing


def forget_watch_rows(install_id: str) -> None:
    try:
        default_watch_store().forget(install_id)
    except sqlite3.Error as exc:
        logger.warning("skill_watch_forget_failed", install_id=install_id, error=str(exc))


def uninstall_now(request: Request, install_id: str) -> UninstallResponse:
    return uninstall_with(request.app.state.services, install_id)


def uninstall_with(services: Any, install_id: str) -> UninstallResponse:
    with services.catalog.ledger() as ledger:
        row = ledger.get(install_id)
        if row is None:
            raise not_found_404(install_id)
        refuse_builtin(row)
        targets = ledger.targets(install_id)
        if row.kind == KIND_MOD:
            catalog_mod_gates.unregister_before_uninstall(targets)
        trashed, missing = trash_targets(
            row,
            targets,
            roots=services.install_roots,
            stamp=trash_stamp(services.clock),
        )
        ledger.delete(install_id)

    prune_theme_pins_with(services, row)
    announce_theme_change(row)
    forget_watch_rows(install_id)
    if row.scope == SCOPE_GLOBAL:
        with closing(services.catalog.open_db()) as conn:
            mark_declined(conn, row.item_id)

    logger.info(
        "skill_uninstalled",
        install_id=install_id,
        item_id=row.item_id,
        scope=row.scope,
        trashed=len(trashed),
        missing=len(missing),
    )
    return UninstallResponse(
        install_id=install_id, trashed=trashed, missing=missing
    )


def patch_now(
    request: Request, install_id: str, body: InstalledPatchRequest
) -> InstalledItem:
    services = request.app.state.services
    with services.catalog.ledger() as ledger:
        current = ledger.get(install_id)
        if current is None:
            raise not_found_404(install_id)
        refuse_builtin(current)
        if body.auto_update and current.kind == KIND_CPLUG:
            raise refuse_409(
                "cplug_never_auto_updates",
                "a plugin is code that runs as a process on this computer, so it never updates itself; "
                "update it by hand and read the sheet again",
            )
        if body.auto_update and current.kind == KIND_MOD:
            raise refuse_409(
                "mod_never_auto_updates",
                "a mod is code that runs with your permissions, so it never updates itself; "
                "update it by hand and read the sheet again",
            )
        if body.auto_update and current.scope != SCOPE_GLOBAL:
            logger.info(
                "skill_auto_update_refused",
                install_id=install_id,
                scope=current.scope,
            )
            raise refuse_409(
                AUTO_UPDATE_GLOBAL_ONLY,
                "auto-update is global only; a project copy is committed "
                "into a repository and shared with whoever checks it out, "
                "so this app never rewrites one unasked",
            )
        try:
            return ledger.update(
                install_id,
                expected_revision=body.expected_revision,
                now=iso_from(services.clock),
                auto_update=body.auto_update,
            )
        except StaleRevision as exc:
            raise stale_409(exc.current)
        except InstallNotFound:
            raise not_found_404(install_id)


def swap_targets(
    row: InstalledItem,
    targets: Tuple[InstallTarget, ...],
    *,
    staged: Path,
    roots: InstallRoots,
    stamp: str,
    exec_paths: frozenset,
) -> None:
    project = project_of(row)
    pending_dir = roots.pending_dir()
    for target in targets:
        live = Path(target.path)
        incoming = live.parent / f"{live.name}{INCOMING_SUFFIX}{stamp}"
        copy_tree(staged, incoming, exec_paths=exec_paths)
        journal = PendingJournal(
            install_id=row.install_id,
            kind=row.kind,
            name=live.name,
            scope=row.scope,
            project_path=project,
            target=str(live),
            staged=str(incoming),
            trash=str(
                trash_root_for(
                    roots, kind=row.kind, harness=target.harness,
                    scope=row.scope, project_path=project, live_path=live,
                )
            ),
            stamp=stamp,
            step=STEP_WRITTEN,
        )
        write_pending(pending_dir, row.install_id, journal)
        apply_swap(journal, roots=roots)


def apply_update_now(
    request: Request,
    *,
    row: InstalledItem,
    version: ItemVersion,
    staged: Any,
    body_sha: str,
    expected_revision: int,
) -> InstalledItem:
    return apply_update_with(
        request.app.state.services,
        row=row,
        version=version,
        staged=staged,
        body_sha=body_sha,
        expected_revision=expected_revision,
    )


def apply_update_with(
    services: Any,
    *,
    row: InstalledItem,
    version: ItemVersion,
    staged: Any,
    body_sha: str,
    expected_revision: int,
) -> InstalledItem:
    roots = services.install_roots
    index_url = services.catalog.index_url()
    stamp = iso_from(services.clock)

    with services.catalog.ledger() as ledger:
        targets = ledger.targets(row.install_id)
        if not targets:
            logger.error(
                "skill_update_no_targets",
                install_id=row.install_id,
                item_id=row.item_id,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"install {row.install_id!r} records no files, so there "
                    "is nothing to replace"
                ),
            )

        write_sidecar(
            staged.path,
            SkillRecord(
                publisher=row.publisher,
                name=row.name,
                version=version.v,
                digest=staged.digest,
                source_index_url=index_url,
                installed_at=stamp,
            ),
        )
        try:
            swap_targets(
                row,
                targets,
                staged=staged.path,
                roots=roots,
                stamp=trash_stamp(services.clock),
                exec_paths=frozenset(executable_members(staged.archive)),
            )
        except OSError as exc:
            journal = pending_path(roots.pending_dir(), row.install_id)
            logger.error(
                "skill_update_failed",
                install_id=row.install_id,
                item_id=row.item_id,
                journal=str(journal),
                error=str(exc),
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"the update could not be written: {exc}. the journal at "
                    f"{journal} is finished or reversed at the next start"
                ),
            )

        try:
            updated = ledger.update(
                row.install_id,
                expected_revision=expected_revision,
                now=stamp,
                version=version.v,
                digest=staged.digest,
                consented_digest=staged.digest,
                consented_body_sha=body_sha,
            )
        except StaleRevision as exc:
            logger.warning(
                "skill_update_raced",
                install_id=row.install_id,
                expected_revision=expected_revision,
                current_revision=exc.current.revision,
            )
            raise stale_409(exc.current)
        except InstallNotFound:
            raise not_found_404(row.install_id)

    drop_theme_run_grant_with(services, updated)
    announce_theme_change(updated)

    logger.info(
        "skill_updated",
        install_id=updated.install_id,
        item_id=updated.item_id,
        version=updated.version,
        targets=len(targets),
    )
    return updated
