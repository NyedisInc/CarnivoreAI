
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional
from src.core.safe_io.atomic_write import DEFAULT_PARENT_MODE, atomic_write_text

PRIVATE_FILE_MODE = 0o600

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    class _NoOpLogger:

        def __getattr__(self, _name: str) -> Callable[..., None]:
            return lambda *a, **k: None

    logger = _NoOpLogger()


def atomic_write_json(path: Path, payload: dict, *, log_event: str, mode: int = PRIVATE_FILE_MODE) -> bool:
    try:
        atomic_write_text(
            path, json.dumps(payload, indent=2, sort_keys=True), mode=mode, parent_mode=DEFAULT_PARENT_MODE,
        )
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.warning(
            log_event, path=str(path), error=f"{type(exc).__name__}: {exc}",
        )
        return False


class UnreadableArtifact(OSError):

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def read_for_update(path: Path, *, log_event: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
    else:
        if isinstance(data, dict):
            return data
        reason = "top level is not an object"
    logger.error(log_event, path=str(path), error=reason)
    raise UnreadableArtifact(path, reason)


def read_json_object(path: Path, *, log_event: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.debug(
            log_event, path=str(path), error=f"{type(exc).__name__}: {exc}",
        )
        return None
    return data if isinstance(data, dict) else None
