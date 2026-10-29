
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.cplugs.sdk import transcript_files as tf
from src.cplugs.save.engine import constants as C

logger = structlog.get_logger()


def default_config_path() -> Path:
    return tf.config_file()


def scope_of(config: Dict[str, Any]) -> str:
    block = config.get(C.SCOPE_CONFIG_BLOCK)
    if block is None:
        return C.DEFAULT_CAPTURE_SCOPE
    value = block.get(C.SCOPE_CONFIG_FIELD) if isinstance(block, dict) else None
    if value is None:
        return C.DEFAULT_CAPTURE_SCOPE
    if value not in C.CAPTURE_SCOPES:
        logger.warning("time_machine_scope_invalid", value=str(value)[:40])
        return C.DEFAULT_CAPTURE_SCOPE
    return value


def read_scope(config_path: Optional[Path] = None) -> str:
    path = config_path or default_config_path()
    try:
        return scope_of(tf.read_config(path))
    except FileNotFoundError:
        return C.DEFAULT_CAPTURE_SCOPE
    except (OSError, ValueError) as exc:
        logger.warning("time_machine_scope_unreadable", path=str(path), error=str(exc))
        return C.DEFAULT_CAPTURE_SCOPE


def set_scope(value: str, config_path: Optional[Path] = None) -> str:
    if value not in C.CAPTURE_SCOPES:
        raise ValueError(f"capture_scope must be one of {', '.join(C.CAPTURE_SCOPES)}")
    path = config_path or default_config_path()

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block = config.get(C.SCOPE_CONFIG_BLOCK)
        if block is not None and not isinstance(block, dict):
            raise ValueError(f"the stored {C.SCOPE_CONFIG_BLOCK} block is not an object")
        if (block or {}).get(C.SCOPE_CONFIG_FIELD) == value:
            return None
        merged = dict(config)
        merged[C.SCOPE_CONFIG_BLOCK] = {**(block or {}), C.SCOPE_CONFIG_FIELD: value}
        return merged

    tf.commit_config(path, mutate)
    logger.info("time_machine_scope_set", capture_scope=value)
    return value
