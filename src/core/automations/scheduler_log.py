
from __future__ import annotations

import json
import logging
import logging.handlers
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = structlog.get_logger()

FILENAME = "automations-scheduler.jsonl"
CONFIG_KEY = "automations_log"
EVENTS = ("scheduled", "claimed", "started", "queued", "delivered", "finished", "failed", "retried", "skipped", "catch_up",
          "created", "edited", "deleted")
DROPPED_FIELDS = frozenset({"text", "argv", "args", "params", "env", "stdout", "stderr", "stdout_tail", "stderr_tail", "prompt",
                            "token", "key", "api_key", "password", "secret", "report"})
VALUE_MAX = 500
READ_SCAN_BYTES = 8 << 20
NOTIFY_INTERVAL_S = 1.0


class LogSettings(BaseModel):
    """How the scheduler log rotates: ``size`` (at ``max_mb``) or ``daily`` (at midnight), keeping ``keep`` old files."""

    model_config = ConfigDict(extra="forbid")
    rotate: Literal["size", "daily"] = "size"
    max_mb: int = Field(default=10, ge=1, le=500)
    keep: int = Field(default=5, ge=1, le=50)


def read_settings(config: Dict[str, Any]) -> LogSettings:
    block = config.get(CONFIG_KEY)
    if block is None:
        return LogSettings()
    try:
        return LogSettings.model_validate(block)
    except ValidationError as exc:
        logger.warning("automations_log_block_invalid", error_count=exc.error_count())
        return LogSettings()


def _clean(value: Any) -> Any:
    from src.core.timers.redact import redact  # noqa: PLC0415

    if isinstance(value, str):
        return redact(value)[:VALUE_MAX]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in DROPPED_FIELDS}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value[:50]]
    return value


class SchedulerLog:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logger = logging.getLogger("carnivore.automations.scheduler_log")
        self._logger.propagate = False
        self._logger.setLevel(logging.INFO)
        self._handler: Optional[logging.Handler] = None
        self.path: Optional[Path] = None
        self.settings = LogSettings()

    def configure(self, log_dir: Path, settings: LogSettings) -> None:
        path = Path(log_dir) / FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        if settings.rotate == "daily":
            handler: logging.Handler = logging.handlers.TimedRotatingFileHandler(
                path, when="midnight", backupCount=settings.keep, encoding="utf-8")
        else:
            handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=settings.max_mb * 1024 * 1024, backupCount=settings.keep, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        with self._lock:
            old, self._handler, self.path, self.settings = self._handler, handler, path, settings
            self._logger.addHandler(handler)
            if old is not None:
                self._logger.removeHandler(old)
                old.close()

    def close(self) -> None:
        with self._lock:
            if self._handler is not None:
                self._logger.removeHandler(self._handler)
                self._handler.close()
            self._handler = None

    def write(self, event: str, **fields: Any) -> None:
        if self._handler is None:
            return
        if event not in EVENTS:
            raise ValueError(f"unknown scheduler log event {event!r}")
        line = json.dumps({"ts": round(time.time(), 3), "event": event, **_clean(fields)}, default=str, sort_keys=True)
        try:
            self._logger.info(line)
        except (OSError, ValueError) as exc:
            logger.warning("automations_log_write_failed", error_type=type(exc).__name__)
            return
        from src.core.resource_push import topics  # noqa: PLC0415
        from src.core.resource_push.notifier import notify_coalesced  # noqa: PLC0415

        notify_coalesced(topics.AUTOMATION_LOG, "all", NOTIFY_INTERVAL_S)

    def _files(self) -> List[Path]:
        if self.path is None:
            return []
        rotated = sorted((p for p in self.path.parent.glob(FILENAME + ".*")), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p for p in [self.path, *rotated] if p.exists()]

    def read(self, automation_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        found: List[Dict[str, Any]] = []
        budget = READ_SCAN_BYTES
        for path in self._files():
            size = path.stat().st_size
            with path.open("rb") as fh:
                if size > budget:
                    fh.seek(size - budget)
                    fh.readline()
                data = fh.read()
            budget -= len(data)
            for raw in reversed(data.splitlines()):
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if automation_id is None or row.get("automation_id") == automation_id:
                    found.append(row)
                    if len(found) >= limit:
                        return found
            if budget <= 0:
                break
        return found


LOG = SchedulerLog()


def write(event: str, **fields: Any) -> None:
    LOG.write(event, **fields)


def start(config_path: Path, log_dir: Path) -> LogSettings:
    try:
        config = json.loads(Path(config_path).expanduser().read_text())
    except (OSError, ValueError) as exc:
        logger.warning("automations_log_config_unreadable", error_type=type(exc).__name__)
        config = {}
    settings = read_settings(config if isinstance(config, dict) else {})
    LOG.configure(log_dir, settings)
    return settings


def save_settings(config_path: Path, settings: LogSettings) -> LogSettings:
    from src.core import config_writer  # noqa: PLC0415

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block = settings.model_dump()
        return None if config.get(CONFIG_KEY) == block else {**config, CONFIG_KEY: block}

    config_writer.commit(Path(config_path).expanduser(), mutate)
    if LOG.path is not None:
        LOG.configure(LOG.path.parent, settings)
    logger.info("automations_log_settings_saved", rotate=settings.rotate, max_mb=settings.max_mb, keep=settings.keep)
    return settings
