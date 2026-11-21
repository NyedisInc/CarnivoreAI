
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

RETIRED_SUFFIX = ".retired"


def retire_metadata_file(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    retired = path.with_name(path.name + RETIRED_SUFFIX)
    os.replace(path, retired)
    logger.info("session_metadata_retired", path=str(path), retired=str(retired))
    return retired
