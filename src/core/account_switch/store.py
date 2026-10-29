
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog
from pydantic import ValidationError

from src.config.provider_account_switch import (
    PROVIDER_ACCOUNT_SWITCH_KEY,
    ProviderAccountSwitchConfig,
    pointer_field,
)
from src.core import config_writer, resource_push
from src.core.resource_push import topics as resource_topics

logger = structlog.get_logger()


def read_block(config: Dict[str, Any]) -> ProviderAccountSwitchConfig:
    block = config.get(PROVIDER_ACCOUNT_SWITCH_KEY)
    if block is None:
        return ProviderAccountSwitchConfig()
    if not isinstance(block, dict):
        logger.warning("invalid_provider_account_switch_block", reason="not_an_object")
        return ProviderAccountSwitchConfig()
    try:
        return ProviderAccountSwitchConfig(**block)
    except (TypeError, ValidationError) as exc:
        logger.warning(
            "invalid_provider_account_switch_block",
            reason=type(exc).__name__,
        )
        return ProviderAccountSwitchConfig()


def read_switch(config_path: Path) -> ProviderAccountSwitchConfig:
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
    change: Dict[str, Any],
    *,
    event: str,
    expect: Optional[Dict[str, Any]] = None,
    **log_context: Any,
) -> Tuple[str, ProviderAccountSwitchConfig]:

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raw = config.get(PROVIDER_ACCOUNT_SWITCH_KEY)
        if raw is not None:
            try:
                ProviderAccountSwitchConfig(**raw) if isinstance(raw, dict) else None
            except (TypeError, ValidationError) as exc:
                raise ValueError("the stored provider_account_switch block is invalid") from exc
            if not isinstance(raw, dict):
                raise ValueError("the stored provider_account_switch block is invalid")
        current = read_block(config)
        if expect is not None:
            stored = current.model_dump()
            if any(stored.get(key) != value for key, value in expect.items()):
                return None
        merged = current.model_dump()
        merged.update(change)
        try:
            updated = ProviderAccountSwitchConfig(**merged)
        except ValidationError as exc:
            raise ValueError(
                exc.errors(include_url=False, include_context=False, include_input=False)
            ) from exc
        if updated == current and PROVIDER_ACCOUNT_SWITCH_KEY in config:
            return None
        return {**config, PROVIDER_ACCOUNT_SWITCH_KEY: updated.model_dump()}

    outcome = config_writer.commit(Path(config_path).expanduser(), mutate)
    now = read_block(outcome.data)
    if outcome.wrote:
        logger.info(event, **log_context)
        resource_push.notify(resource_topics.ACCOUNT_SWITCH)
    return outcome.status, now


def set_active(
    config_path: Path,
    provider: str,
    account_id: Optional[str],
    *,
    expect: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ProviderAccountSwitchConfig]:
    return _commit(
        config_path,
        {pointer_field(provider): account_id},
        expect=expect,
        event="provider_account_active_set",
        provider=provider,
        account_id=account_id,
    )


def set_auto(
    config_path: Path, *, enabled: bool, threshold_percent: Optional[int] = None
) -> Tuple[str, ProviderAccountSwitchConfig]:
    change: Dict[str, Any] = {"auto_switch": bool(enabled)}
    if threshold_percent is not None:
        change["threshold_percent"] = threshold_percent
    return _commit(
        config_path,
        change,
        event="provider_account_auto_switch_set",
        enabled=bool(enabled),
        threshold_percent=threshold_percent,
    )
