
from __future__ import annotations

import os
from pathlib import Path

import structlog

from src.core.sessions.ports import InstallRoots
from src.core.skills.journal_containment import journal_refusal
from src.core.skills.targets import copy_tree, remove_tree
from src.core.skills.update_journal import (
    JOURNAL_MODE,
    PendingJournal,
    clear_pending,
    displaced_path,
    read_pending,
)
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()


OUTCOME_FINISHED = "finished"

OUTCOME_REVERSED = "reversed"

OUTCOME_ALREADY_COMPLETE = "already_complete"

OUTCOME_NOTHING = "nothing_to_recover"

OUTCOME_REFUSED = "refused"

REFUSED_DIR_NAME = "refused"


def list_pending(pending_dir: Path) -> tuple[Path, ...]:
    try:
        with os.scandir(pending_dir) as entries:
            found = [
                Path(entry.path)
                for entry in entries
                if entry.is_file() and entry.name.endswith(".json")
            ]
    except FileNotFoundError:
        return ()
    except OSError as exc:
        logger.warning(
            "skill_journal_dir_unreadable", directory=str(pending_dir), error=str(exc)
        )
        return ()
    return tuple(sorted(found))


def refuse_journal(path: Path, journal: PendingJournal, reason: str) -> None:
    refused_dir = path.parent / REFUSED_DIR_NAME
    assert_test_write_allowed(refused_dir)
    refused_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(refused_dir, JOURNAL_MODE)

    destination = refused_dir / path.name
    assert_test_write_allowed(path)
    assert_test_write_allowed(destination)
    os.replace(path, destination)
    logger.info(
        "skill_journal_moved_aside",
        install_id=journal.install_id,
        reason=reason,
        destination=str(destination),
    )


def recover_one(
    path: Path, journal: PendingJournal, *, roots: InstallRoots
) -> str:
    refusal = journal_refusal(journal, roots=roots)
    if refusal is not None:
        logger.warning(
            "catalog_journal_refused",
            install_id=journal.install_id,
            code=refusal.code,
            detail=refusal.detail,
            target=journal.target,
            staged=journal.staged,
            trash=journal.trash,
        )
        refuse_journal(path, journal, refusal.code)
        return OUTCOME_REFUSED

    staged = Path(journal.staged)
    target = Path(journal.target)
    displaced = displaced_path(journal)

    staged_there = os.path.lexists(staged)
    target_there = os.path.lexists(target)

    if staged_there and not target_there:
        copy_tree(staged, target)
        remove_tree(staged)
        outcome = OUTCOME_FINISHED
    elif not target_there and os.path.lexists(displaced):
        copy_tree(displaced, target)
        remove_tree(displaced)
        if staged_there:
            remove_tree(staged)
        outcome = OUTCOME_REVERSED
    elif staged_there:
        remove_tree(staged)
        outcome = OUTCOME_REVERSED
    elif target_there:
        outcome = OUTCOME_ALREADY_COMPLETE
    else:
        outcome = OUTCOME_NOTHING

    clear_pending(path)
    logger.info(
        "skill_update_recovered",
        install_id=journal.install_id,
        outcome=outcome,
        step=journal.step,
        target=journal.target,
    )
    return outcome


def recover_pending(pending_dir: Path, roots: InstallRoots) -> dict[str, int]:
    expected = roots.pending_dir()
    if Path(pending_dir) != expected:
        raise ValueError(
            f"{pending_dir} is not this install's journal directory "
            f"({expected}); recovery deletes every journal it reads, so it "
            "never runs against a directory it was not pointed at"
        )
    counts: dict[str, int] = {
        OUTCOME_FINISHED: 0,
        OUTCOME_REVERSED: 0,
        OUTCOME_ALREADY_COMPLETE: 0,
        OUTCOME_NOTHING: 0,
        OUTCOME_REFUSED: 0,
        "unreadable": 0,
    }
    for path in list_pending(pending_dir):
        journal = read_pending(path)
        if journal is None:
            counts["unreadable"] += 1
            continue
        try:
            counts[recover_one(path, journal, roots=roots)] += 1
        except OSError as exc:
            logger.warning(
                "skill_update_recovery_failed",
                path=str(path),
                install_id=journal.install_id,
                error=str(exc),
            )
    return counts
