
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core import config_writer
from src.core.log_level import live

logger = structlog.get_logger()

LOG_LEVEL_KEY = "log_level"


def read_chosen(config: Dict[str, Any]) -> Optional[str]:
    raw = config.get(LOG_LEVEL_KEY)
    if raw is None:
        return None
    chosen = live.normalize(raw)
    if chosen is None:
        logger.warning("invalid_log_level_setting", reason=type(raw).__name__)
    return chosen


def read_chosen_from_file(config_path: Path) -> Optional[str]:
    try:
        data = json.loads(Path(config_path).expanduser().read_text())
    except (OSError, ValueError):
        return None
    return read_chosen(data) if isinstance(data, dict) else None


def env_name(env_value: str) -> str:
    return live.normalize(env_value) or live.DEFAULT_LEVEL


def effective_name(env_value: str, config_path: Path) -> str:
    return read_chosen_from_file(config_path) or env_name(env_value)


def set_chosen(config_path: Path, level: Optional[str]) -> bool:
    if level is not None and level not in live.LEVEL_NAMES:
        raise ValueError(f"level must be one of {', '.join(live.LEVEL_NAMES)}")

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if config.get(LOG_LEVEL_KEY) == level:
            return None
        updated = {k: v for k, v in config.items() if k != LOG_LEVEL_KEY}
        if level is not None:
            updated[LOG_LEVEL_KEY] = level
        return updated

    outcome = config_writer.commit(Path(config_path).expanduser(), mutate)
    if outcome.wrote:
        logger.info("log_level_setting_stored", level=level)
    return outcome.wrote
