
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Callable, Iterable

import structlog

from src.core.sessions.ports import InstallRoots
from src.core.live_install_roots import TRASH_DIR_NAME
from src.core.skills.targets import ensure_trash_gitignore, remove_tree

logger = structlog.get_logger()

STAGING_TTL_SECONDS = 60 * 60

TRASH_TTL_SECONDS = 14 * 24 * 60 * 60

SWEEP_INTERVAL_SECONDS = 6 * 60 * 60

MAX_CONCURRENT_STAGING = 8

PROJECT_TRASH_PARENTS = (".claude", ".agents", ".codex")

KEEP_ENTRY = ".gitignore"


def _entry_age_seconds(entry: os.DirEntry, now: float) -> float | None:
    try:
        return now - entry.stat(follow_symlinks=False).st_mtime
    except OSError as exc:
        logger.warning(
            "skill_sweep_entry_unreadable", path=entry.path, error=str(exc)
        )
        return None


def sweep_directory(directory: Path, ttl_seconds: int, now: float) -> int:
    try:
        with os.scandir(directory) as entries:
            candidates = list(entries)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        logger.warning(
            "skill_sweep_directory_unreadable",
            directory=str(directory),
            error=str(exc),
        )
        return 0

    removed = 0
    for entry in candidates:
        if entry.name == KEEP_ENTRY:
            continue
        age = _entry_age_seconds(entry, now)
        if age is None or age < ttl_seconds:
            continue
        try:
            remove_tree(directory / entry.name)
            removed += 1
        except OSError as exc:
            logger.warning(
                "skill_sweep_removal_failed", path=entry.path, error=str(exc)
            )
    return removed


def sweep_project_trashes(
    project_roots: Iterable[str], ttl_seconds: int, now: float
) -> int:
    removed = 0
    for project in project_roots:
        for parent in PROJECT_TRASH_PARENTS:
            base = Path(project) / parent
            trash = base / TRASH_DIR_NAME
            if base.is_symlink() or trash.is_symlink() or not trash.is_dir():
                continue
            try:
                ensure_trash_gitignore(trash)
            except OSError as exc:
                logger.warning(
                    "skill_trash_gitignore_failed", path=str(trash), error=str(exc)
                )
            removed += sweep_directory(trash, ttl_seconds, now)
    return removed


class SkillSweeper:

    def __init__(
        self,
        *,
        install_roots: InstallRoots,
        staging_ttl_seconds: int = STAGING_TTL_SECONDS,
        trash_ttl_seconds: int = TRASH_TTL_SECONDS,
        interval_seconds: int = SWEEP_INTERVAL_SECONDS,
        project_roots: Callable[[], Iterable[str]] = lambda: (),
    ) -> None:
        self._install_roots = install_roots
        self._project_roots = project_roots
        self.staging_ttl_seconds = staging_ttl_seconds
        self.trash_ttl_seconds = trash_ttl_seconds
        self.interval_seconds = interval_seconds

    async def run(self) -> None:
        logger.info(
            "skill_sweeper_started",
            interval_seconds=self.interval_seconds,
            staging_ttl_seconds=self.staging_ttl_seconds,
            trash_ttl_seconds=self.trash_ttl_seconds,
        )
        try:
            await self.run_boot_pass()
        except asyncio.CancelledError:
            logger.info("skill_sweeper_stopping")
            raise
        except Exception as exc:
            logger.warning("skill_sweep_boot_pass_failed", error=str(exc))

        while True:
            try:
                await asyncio.sleep(self.interval_seconds)
                await self.sweep_now()
            except asyncio.CancelledError:
                logger.info("skill_sweeper_stopping")
                raise
            except Exception as exc:
                logger.warning("skill_sweep_iteration_failed", error=str(exc))

    async def run_boot_pass(self) -> dict:
        recovered = await asyncio.to_thread(self._recover_once)
        swept = await self.sweep_now()
        return {**swept, "recovered": recovered}

    def _recover_once(self) -> dict:
        from src.core.skills.updates import recover_pending

        pending = self._install_roots.pending_dir()
        try:
            return recover_pending(pending, self._install_roots)
        except (OSError, ValueError) as exc:
            logger.warning(
                "skill_journal_recovery_failed",
                directory=str(pending),
                error=str(exc),
            )
            return {}

    async def sweep_now(self) -> dict:
        return await asyncio.to_thread(self._sweep_once)

    def _sweep_once(self) -> dict:
        started = time.perf_counter()
        now = time.time()

        staging_removed = sweep_directory(
            self._install_roots.staging_dir(), self.staging_ttl_seconds, now
        )

        trash_removed = 0
        for target in self._install_roots.targets_for("skill", "global", None):
            trash_removed += sweep_directory(
                self._install_roots.trash_dir(target.harness, "global", None),
                self.trash_ttl_seconds,
                now,
            )
        for target in self._install_roots.legacy_targets_for(
            "skill", "global", None
        ):
            trash_removed += sweep_directory(
                target.leaf_dir.parent / TRASH_DIR_NAME,
                self.trash_ttl_seconds,
                now,
            )

        try:
            trash_removed += sweep_project_trashes(
                self._project_roots(), self.trash_ttl_seconds, now
            )
        except (OSError, ValueError) as exc:
            logger.warning("skill_project_trash_sweep_failed", error=str(exc))

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if staging_removed or trash_removed:
            logger.info(
                "skill_sweep_complete",
                staging_removed=staging_removed,
                trash_removed=trash_removed,
                elapsed_ms=elapsed_ms,
            )
        else:
            logger.debug("skill_sweep_complete", elapsed_ms=elapsed_ms)
        return {
            "staging_removed": staging_removed,
            "trash_removed": trash_removed,
        }
