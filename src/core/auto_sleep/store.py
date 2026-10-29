
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
from pydantic import ValidationError

from src.config.auto_sleep import AUTO_SLEEP_KEY, AutoSleepConfig
from src.core import config_writer

logger = structlog.get_logger()


class StoredBlockInvalid(ValueError):
    pass


def read_block(config: Dict[str, Any]) -> AutoSleepConfig:
    block = config.get(AUTO_SLEEP_KEY)
    if block is None:
        return AutoSleepConfig()
    if not isinstance(block, dict):
        logger.warning("invalid_auto_sleep_block", reason="not_an_object")
        return AutoSleepConfig()
    try:
        return AutoSleepConfig(**block)
    except (TypeError, ValidationError) as exc:
        logger.warning("invalid_auto_sleep_block", reason=type(exc).__name__)
        return AutoSleepConfig()


def read(config_path: Path) -> AutoSleepConfig:
    resolved = Path(config_path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"Auth config file not found: {resolved}")
    try:
        data = json.loads(resolved.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {resolved}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config shape in {resolved}: expected an object")
    return read_block(data)


def _commit(
    config_path: Path,
    change: Any,
    *,
    event: str,
    **log_context: Any,
) -> Tuple[str, AutoSleepConfig]:

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raw = config.get(AUTO_SLEEP_KEY)
        if raw is not None:
            if not isinstance(raw, dict):
                raise StoredBlockInvalid("the stored auto_sleep block is invalid")
            try:
                AutoSleepConfig(**raw)
            except (TypeError, ValidationError) as exc:
                raise StoredBlockInvalid("the stored auto_sleep block is invalid") from exc
        current = read_block(config)
        merged = current.model_dump()
        merged.update(change(current))
        try:
            updated = AutoSleepConfig(**merged)
        except ValidationError as exc:
            raise ValueError(
                exc.errors(include_url=False, include_context=False, include_input=False)
            ) from exc
        if updated == current and AUTO_SLEEP_KEY in config:
            return None
        return {**config, AUTO_SLEEP_KEY: updated.model_dump()}

    outcome = config_writer.commit(Path(config_path).expanduser(), mutate)
    now = read_block(outcome.data)
    if outcome.wrote:
        logger.info(event, **log_context)
    return outcome.status, now


def set_settings(
    config_path: Path,
    *,
    enabled: Optional[bool] = None,
    idle_minutes: Optional[int] = None,
    unread_blocks_sleep: Optional[bool] = None,
    unread_idle_minutes: Optional[int] = None,
) -> Tuple[str, AutoSleepConfig]:
    fields: Dict[str, Any] = {}
    if enabled is not None:
        fields["enabled"] = bool(enabled)
    if idle_minutes is not None:
        fields["idle_minutes"] = idle_minutes
    if unread_blocks_sleep is not None:
        fields["unread_blocks_sleep"] = bool(unread_blocks_sleep)
    if unread_idle_minutes is not None:
        fields["unread_idle_minutes"] = unread_idle_minutes
    return _commit(
        config_path,
        lambda _current: fields,
        event="auto_sleep_settings_set",
        enabled=enabled,
        idle_minutes=idle_minutes,
        unread_blocks_sleep=unread_blocks_sleep,
        unread_idle_minutes=unread_idle_minutes,
    )


def set_keep_awake(
    config_path: Path, session_uuid: str, keep_awake: bool
) -> Tuple[str, AutoSleepConfig]:

    def change(current: AutoSleepConfig) -> Dict[str, Any]:
        kept = [item for item in current.keep_awake if item != session_uuid]
        if keep_awake:
            kept.append(session_uuid)
        return {"keep_awake": kept}

    return _commit(
        config_path,
        change,
        event="auto_sleep_keep_awake_set",
        session_uuid=session_uuid,
        keep_awake=bool(keep_awake),
    )


def set_mac_awake_always(config_path: Path, always: bool) -> Tuple[str, AutoSleepConfig]:
    return _commit(
        config_path,
        lambda _current: {"mac_awake_always": bool(always)},
        event="auto_sleep_mac_awake_always_set",
        always=bool(always),
    )
