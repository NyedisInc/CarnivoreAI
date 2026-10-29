
import asyncio
import os
import sqlite3
import stat as stat_module
import time
from collections.abc import Callable
from pathlib import Path

import structlog

from src.core.uploads.bucket_guard import BUCKET_GITIGNORE, SweepOutcome, SweepVerdict, sweep_verdicts

logger = structlog.get_logger()


def datastore_project_paths(view) -> list[str] | None:
    try:
        if not view.writable:
            logger.warning(
                "project_list_unreadable",
                error="datastore view is not writable, projects could not be read",
            )
            return None
        projects = view.projects
    except AttributeError as exc:
        logger.warning("project_list_unreadable", error=str(exc))
        return None
    if projects is None:
        logger.warning("project_list_unreadable", error="projects is None")
        return None

    paths: list[str] = []
    try:
        for project in projects:
            path = project["path"]
            if not isinstance(path, str) or not path.strip():
                logger.warning(
                    "project_list_unreadable",
                    error=f"project entry has an unusable path: {path!r}",
                )
                return None
            paths.append(path)
    except (AttributeError, TypeError, KeyError) as exc:
        logger.warning("project_list_unreadable", error=str(exc))
        return None
    return paths


class UploadSweeper:

    def __init__(
        self,
        *,
        ttl_seconds: int,
        interval_seconds: int,
        project_paths: list[str] | None,
        default_dir: Path,
        project_paths_provider: Callable[[], list[str] | None] | None = None,
    ):
        self.ttl_seconds = ttl_seconds
        self.interval_seconds = interval_seconds
        self.project_paths = None if project_paths is None else list(project_paths)
        self.default_dir = default_dir
        self._project_paths_provider = project_paths_provider

    async def _refresh_project_paths(self) -> None:
        if self._project_paths_provider is None:
            return
        try:
            paths = await asyncio.to_thread(self._project_paths_provider)
        except (OSError, sqlite3.Error, ValueError) as exc:
            logger.warning("upload_sweep_project_refresh_failed", error=str(exc))
            return
        self.project_paths = None if paths is None else list(paths)

    async def run(self) -> None:
        logger.info(
            "upload_sweeper_started",
            ttl_seconds=self.ttl_seconds,
            interval_seconds=self.interval_seconds,
            base_paths=(
                "undetermined"
                if self.project_paths is None
                else len(self.project_paths) + 1
            ),
        )

        while True:
            try:
                await asyncio.sleep(self.interval_seconds)
                await self._sweep_once()
            except asyncio.CancelledError:
                logger.info("upload_sweeper_stopping")
                raise
            except Exception as exc:
                logger.warning(
                    "upload_sweep_iteration_failed",
                    error=str(exc),
                )

    async def sweep_now(self) -> dict:
        return await self._sweep_once()

    async def _sweep_once(self) -> dict:
        started = time.perf_counter()
        await self._refresh_project_paths()

        if self.project_paths is None:
            logger.warning(
                "upload_sweep_skipped_project_list_undetermined",
                default_dir=str(self.default_dir),
            )
            return {
                "files_pruned": 0,
                "bytes_freed": 0,
                "bases_refused": 0,
                "project_list_determined": False,
            }

        cutoff = time.time() - self.ttl_seconds
        bases = (*self.project_paths, str(self.default_dir))

        total_files = 0
        total_bytes = 0
        refused = 0

        for base in bases:
            try:
                files, freed, was_refused = await asyncio.to_thread(
                    _prune_base, base, cutoff
                )
                total_files += files
                total_bytes += freed
                refused += int(was_refused)
            except Exception as exc:
                refused += 1
                logger.warning(
                    "upload_sweep_partial_error",
                    base_path=base,
                    error=str(exc),
                )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "upload_sweep_complete",
            files_pruned=total_files,
            bytes_freed=total_bytes,
            bases_refused=refused,
            elapsed_ms=elapsed_ms,
        )
        return {
            "files_pruned": total_files,
            "bytes_freed": total_bytes,
            "bases_refused": refused,
            "project_list_determined": True,
        }


def _prune_base(base: str, cutoff: float) -> tuple[int, int, bool]:
    totals = (0, 0, False)
    for verdict in sweep_verdicts(base):
        files, freed, refused = _prune_verdict(base, verdict, cutoff)
        totals = (totals[0] + files, totals[1] + freed, totals[2] or refused)
    return totals


def _prune_verdict(base: str, verdict: SweepVerdict, cutoff: float) -> tuple[int, int, bool]:
    if verdict.outcome is SweepOutcome.REFUSED:
        logger.warning(
            "upload_sweep_base_refused",
            base_path=str(base),
            reason=verdict.reason,
        )
        return (0, 0, True)

    if verdict.outcome is SweepOutcome.SKIP:
        return (0, 0, False)

    bucket = verdict.bucket
    assert bucket is not None

    files_pruned = 0
    bytes_freed = 0

    try:
        with os.scandir(bucket) as entries:
            candidates = list(entries)
    except OSError as exc:
        logger.warning(
            "upload_sweep_base_refused",
            base_path=str(base),
            reason=f"bucket became unreadable ({exc})",
        )
        return (0, 0, True)

    for entry in candidates:
        if entry.name == BUCKET_GITIGNORE:
            continue
        try:
            entry_stat = entry.stat(follow_symlinks=False)
            mode = entry_stat.st_mode
            if not (
                stat_module.S_ISREG(mode) or stat_module.S_ISLNK(mode)
            ):
                continue
            if entry_stat.st_mtime >= cutoff:
                continue
            size = entry_stat.st_size
            os.unlink(entry.path)
            files_pruned += 1
            bytes_freed += size
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning(
                "upload_sweep_file_error",
                path=entry.path,
                error=str(exc),
            )

    try:
        with os.scandir(bucket) as left:
            names = {entry.name for entry in left}
        if names <= {BUCKET_GITIGNORE}:
            if names:
                os.unlink(bucket / BUCKET_GITIGNORE)
            bucket.rmdir()
    except OSError:
        pass

    return (files_pruned, bytes_freed, False)
