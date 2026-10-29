
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import structlog

from src.core.sessions.ports import InstallRoots
from src.core.skills.targets import remove_tree, swap_in
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

STEP_WRITTEN = 0

STEP_SWAPPING = 1

JOURNAL_MODE = 0o700


@dataclass(frozen=True)
class PendingJournal:

    install_id: str
    kind: str
    name: str
    scope: str
    project_path: Optional[str]
    target: str
    staged: str
    trash: str
    stamp: str
    step: int




def pending_path(pending_dir: Path, install_id: str) -> Path:
    if not install_id.strip() or "/" in install_id or "\\" in install_id:
        raise ValueError(
            f"unusable install id {install_id!r}: it becomes a filename, so "
            "a separator in it would aim the write elsewhere"
        )
    return pending_dir / f"{install_id}.json"


def write_pending(
    pending_dir: Path, install_id: str, journal: PendingJournal
) -> Path:
    assert_test_write_allowed(pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(pending_dir, JOURNAL_MODE)
    destination = pending_path(pending_dir, install_id)
    assert_test_write_allowed(destination)
    destination.write_text(
        json.dumps(asdict(journal), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "skill_update_journal_written",
        install_id=install_id,
        step=journal.step,
        target=journal.target,
    )
    return destination


def read_pending(path: Path) -> Optional[PendingJournal]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("skill_journal_unreadable", path=str(path), error=str(exc))
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("skill_journal_malformed", path=str(path), error=str(exc))
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "skill_journal_malformed",
            path=str(path),
            error=f"top level is {type(parsed).__name__}, not an object",
        )
        return None

    fields = (
        "install_id",
        "kind",
        "name",
        "scope",
        "project_path",
        "target",
        "staged",
        "trash",
        "stamp",
        "step",
    )
    missing = [field for field in fields if field not in parsed]
    if missing:
        logger.warning(
            "skill_journal_malformed",
            path=str(path),
            error=f"missing required fields: {sorted(missing)}",
        )
        return None

    try:
        project_path = parsed["project_path"]
        return PendingJournal(
            install_id=str(parsed["install_id"]),
            kind=str(parsed["kind"]),
            name=str(parsed["name"]),
            scope=str(parsed["scope"]),
            project_path=None if project_path is None else str(project_path),
            target=str(parsed["target"]),
            staged=str(parsed["staged"]),
            trash=str(parsed["trash"]),
            stamp=str(parsed["stamp"]),
            step=int(parsed["step"]),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("skill_journal_malformed", path=str(path), error=str(exc))
        return None


def clear_pending(path: Path) -> None:
    remove_tree(path)
    logger.debug("skill_update_journal_cleared", path=str(path))


def displaced_path(journal: PendingJournal) -> Path:
    return Path(journal.trash) / f"{Path(journal.target).name}-{journal.stamp}"


def apply_swap(journal: PendingJournal, *, roots: InstallRoots) -> Path:
    pending_dir = roots.pending_dir()
    path = write_pending(
        pending_dir,
        journal.install_id,
        PendingJournal(
            install_id=journal.install_id,
            kind=journal.kind,
            name=journal.name,
            scope=journal.scope,
            project_path=journal.project_path,
            target=journal.target,
            staged=journal.staged,
            trash=journal.trash,
            stamp=journal.stamp,
            step=STEP_SWAPPING,
        ),
    )
    displaced = swap_in(
        Path(journal.staged),
        Path(journal.target),
        trash_root=Path(journal.trash),
        stamp=journal.stamp,
    )
    clear_pending(path)
    logger.info(
        "skill_update_applied",
        install_id=journal.install_id,
        target=journal.target,
        displaced=str(displaced),
    )
    return displaced
