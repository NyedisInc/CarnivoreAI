
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.config.retention import RetentionConfig
from src.core.retention import bundles, db_backups, logs, scratch
from src.core.retention.drive import Drive, require_drive
from src.core.retention.errors import DriveNotReadyError, RetentionError, ToolMissingError
from src.core.retention.paths import RetentionPaths
from src.core.retention.report import DONE, FAILED, PLANNED, SKIPPED, Action, RetentionReport

logger = structlog.get_logger()


def _plan_all(paths: RetentionPaths, cfg: RetentionConfig, report: RetentionReport) -> List[Action]:
    jobs = (
        ("db_backups", lambda: db_backups.plan(paths.state_dir, paths.drive_root, cfg.keep_db_backups)),
        ("bundles", lambda: bundles.plan(paths.rollback_dir, paths.drive_root, cfg.keep_rollback_bundles)),
        ("logs", lambda: logs.plan(paths.menubar_log_dir, paths.drive_root, cfg.menubar_log_cap_mb)),
        ("scratch", lambda: scratch.plan(paths, cfg.scratch_idle_hours)),
    )
    actions: List[Action] = []
    for name, job in jobs:
        try:
            actions.extend(job())
        except OSError as exc:
            logger.warning("retention_plan_failed", job=name, error=str(exc))
            report.errors.append(f"{name}: could not plan: {exc}")
    return actions


def _apply(action: Action, drive: Optional[Drive], paths: RetentionPaths, cfg: RetentionConfig) -> str:
    if action.task == "scratch":
        return scratch.apply(action, paths, cfg.scratch_idle_hours)
    assert drive is not None
    if action.task == "bundles":
        return bundles.apply(action, drive, paths)
    return (db_backups if action.task == "db_backups" else logs).apply(action, drive)


class RetentionService:

    def __init__(self, paths_provider: Callable[[], RetentionPaths], config_provider: Callable[[], RetentionConfig]) -> None:
        self._paths, self._config = paths_provider, config_provider
        self._lock = threading.Lock()
        self._last: Optional[RetentionReport] = None

    def config(self) -> RetentionConfig:
        return self._config()

    def run(self, dry_run: bool, should_stop: Callable[[], bool] = lambda: False) -> RetentionReport:
        report = RetentionReport(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), dry_run=dry_run)
        if not self._lock.acquire(blocking=False):
            report.errors.append("a retention run is already in progress")
            return report
        try:
            paths, cfg = self._paths(), self._config()
            drive: Optional[Drive] = None
            try:
                drive = require_drive(paths)
                report.drive_ready = True
            except DriveNotReadyError as exc:
                report.drive_detail = str(exc)
                logger.warning("retention_drive_not_ready", detail=str(exc), dry_run=dry_run)
            report.actions = _plan_all(paths, cfg, report)
            if not dry_run:
                self._carry_out(report, drive, paths, cfg, should_stop)
                self._last = report
            logger.info("retention_run", dry_run=dry_run, drive_ready=report.drive_ready, **report.counts())
            return report
        finally:
            self._lock.release()

    @staticmethod
    def _carry_out(report: RetentionReport, drive: Optional[Drive], paths: RetentionPaths, cfg: RetentionConfig,
                   should_stop: Callable[[], bool]) -> None:
        for action in report.actions:
            if action.status != PLANNED:
                continue
            if should_stop() or (drive is None and action.task != "scratch"):
                action.status, action.detail = SKIPPED, report.drive_detail or "stopped before this action"
                continue
            try:
                action.detail = _apply(action, drive, paths, cfg)
                action.status = DONE
            except (RetentionError, ToolMissingError, OSError) as exc:
                action.status, action.detail = FAILED, str(exc)
                logger.warning("retention_action_failed", task=action.task, source=str(action.source), error=str(exc))

    def status(self) -> Dict[str, Any]:
        return {"enabled": self._config().enabled, "config": self._config().model_dump(),
                "running": self._lock.locked(), "last_run": self._last.to_dict() if self._last else None}


_service: Optional[RetentionService] = None


def get_service() -> RetentionService:
    global _service
    if _service is None:
        from src.config import settings
        from src.core.retention.paths import default_paths

        _service = RetentionService(lambda: default_paths(Path(settings.get_state_dir())),
                                    lambda: settings.load_auth_config().retention)
    return _service
