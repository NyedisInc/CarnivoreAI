
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.resource_push import topics

logger = structlog.get_logger()

CONFIG_KEY = "automations_paused"


_cache: Dict[str, Tuple[Tuple[int, int], bool]] = {}
_cache_lock = threading.Lock()


def _invalidate(path: Path) -> None:
    with _cache_lock:
        _cache.pop(str(path), None)


def config_path() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.auth_config_file).expanduser()


def is_paused(path: Optional[Path] = None) -> bool:
    from src.core import config_writer  # noqa: PLC0415

    target = path or config_path()
    try:
        info = os.stat(target)
    except OSError:
        info = None
    stamp = (info.st_mtime_ns, info.st_size) if info else None
    if stamp is not None:
        with _cache_lock:
            hit = _cache.get(str(target))
        if hit is not None and hit[0] == stamp:
            return hit[1]
    try:
        config: Dict[str, Any] = config_writer.read_config(target)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("automations_pause_config_unreadable", error_type=type(exc).__name__)
        return False
    paused = isinstance(config, dict) and config.get(CONFIG_KEY) is True
    if stamp is not None:
        with _cache_lock:
            _cache[str(target)] = (stamp, paused)
    return paused


def set_paused(paused: bool, path: Optional[Path] = None) -> bool:
    from src.core import config_writer  # noqa: PLC0415

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None if config.get(CONFIG_KEY) is paused else {**config, CONFIG_KEY: paused}

    outcome = config_writer.commit(path or config_path(), mutate)
    _invalidate(path or config_path())
    if outcome.wrote:
        resource_push.notify(topics.AUTOMATIONS)
    logger.info("automations_pause_saved", paused=paused, changed=outcome.wrote)
    return paused
