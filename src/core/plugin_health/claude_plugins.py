
from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from src.core.skill_watch.measure import TooLarge
from src.core.skill_watch.sentinel import measure_folder

logger = structlog.get_logger()


def measured_digest(folder: Path) -> Optional[str]:
    try:
        digest, _entries, anomalies = measure_folder(folder)
    except (TooLarge, OSError) as exc:
        logger.info("plugin_health_digest_unmeasured", error_type=type(exc).__name__)
        return None
    return f"anomalous:{digest}" if anomalies else digest
