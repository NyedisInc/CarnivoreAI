
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.core.safe_file_write import write_private_file

STARTUP_ERROR_DIR = Path.home() / "Library" / "Logs" / "Carnivore"
STARTUP_ERROR_NAME = "startup-error.log"
STARTUP_ERROR_FILE = STARTUP_ERROR_DIR / STARTUP_ERROR_NAME
STARTUP_ERROR_MODE = 0o600


def write_startup_error(message: str) -> Optional[Path]:
    try:
        return write_private_file(
            STARTUP_ERROR_DIR, STARTUP_ERROR_NAME, message.encode("utf-8"), STARTUP_ERROR_MODE
        )
    except OSError:
        return None
