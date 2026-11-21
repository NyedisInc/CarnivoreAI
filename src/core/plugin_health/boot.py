
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Optional

import structlog

from src.core.plugin_health.gather import build_report
from src.core.plugin_health.model import HealthReport
from src.plugins.host.runtime import RegistryError

logger = structlog.get_logger()


def log_report(report: HealthReport) -> None:
    logger.info("plugin_health_boot", **report.counts(), orphan_data=len(report.orphan_data), removed=len(report.removed),
                stale_state=len(report.stale_state), problems=list(report.problems),
                registry_generation=report.registry_generation, registry_source=report.registry_source)


async def run_boot_report(host: Any, live: Optional[Any]) -> Optional[HealthReport]:
    try:
        report = await asyncio.to_thread(build_report, host, live)
    except (OSError, sqlite3.Error, ValueError, KeyError, RegistryError) as exc:
        logger.warning("plugin_health_boot_failed", error_type=type(exc).__name__)
        return None
    log_report(report)
    return report
