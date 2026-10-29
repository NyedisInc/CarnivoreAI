
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

# could not
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
    """Finish or reverse one interrupted update, then delete its journal.

    Description: decided from THE FILESYSTEM, never from ``step``. Four
      states, and each one has exactly one safe answer. The staged copy
      present with the target gone is the middle of a swap and is
      FINISHED, because the new folder has already been verified and the
      old one is safe in the trash. Everything else is REVERSED: put the
      displaced folder back if the target is missing, and drop the staged
      copy, because a staged copy nobody is mid-swap on is debris.
      CONTAINMENT IS CHECKED FIRST, BEFORE ANY OF THE FOUR STATES IS EVEN
      LOOKED FOR. Every path below came out of a file on disk, and the
      first thing this function does with one is hand it to ``copy_tree``
      or ``remove_tree``. So a journal naming paths this app could not
      have produced is moved aside and acted on in no way at all: nothing
      renamed, nothing copied, nothing deleted.
    Inputs: path (Path) - the journal file. journal (PendingJournal).
      roots (InstallRoots) - keyword only, with NO default, because a
      default would be a second way to find a person's home directory and
      because containment cannot be decided without it.
    Output: str - one of the five ``OUTCOME_*`` constants.
    Raises: OutsideTempWriteError: a test run aimed this at a real path.
    Example: recover_one(p, read_pending(p), roots=services.install_roots)
    """
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
    """Finish or reverse every interrupted update found at boot.

    Description: one journal at a time, and a failure on one is logged and
      does NOT stop the others: a single unrecoverable update must not
      leave every other one in flight for ever. A journal that cannot be
      parsed is left ALONE, because acting on a description this pass
      could not read would be acting on a guess.
    Inputs: pending_dir (Path) - from ``InstallRoots.pending_dir()``.
      roots (InstallRoots) - the port, used to CONFIRM that the directory
      handed in is the journal directory. This function deletes every
      ``.json`` file it processes, so a caller that passed the staging
      directory or a project folder by mistake would have it emptied. The
      check costs one call and makes that impossible.
    Output: dict[str, int] - one count per outcome, plus ``unreadable``.
    Raises: ValueError when ``pending_dir`` is not the port's own.
    Example: recover_pending(roots.pending_dir(), roots)["finished"]
    """
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
