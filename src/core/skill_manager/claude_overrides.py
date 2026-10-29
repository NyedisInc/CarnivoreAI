
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core import config_writer
from src.core.skill_manager.types import CLAUDE_STATES, PLUGIN_NO_TOGGLE_REASON, OverrideError
from src.core.skills.roots import unsafe_name_reason
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

MAX_SETTINGS_BYTES = 2 * 1024 * 1024


def read_skill_overrides(path: str) -> Optional[Dict[str, str]]:
    real = os.path.realpath(path)
    try:
        if os.path.getsize(real) > MAX_SETTINGS_BYTES:
            logger.warning("skill_manager_settings_too_large", path=real)
            return None
        with open(real, "rb") as handle:
            data = json.loads(handle.read())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("skill_manager_settings_unparseable", path=real, error=type(exc).__name__)
        return None
    block = data.get("skillOverrides") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return {}
    out = {k: v for k, v in block.items() if isinstance(k, str) and v in CLAUDE_STATES}
    if len(out) != len(block):
        logger.warning(
            "skill_manager_override_values_ignored",
            path=real,
            keys=sorted(str(k) for k in block if k not in out),
        )
    return out


SYNCED_PREFIX = "anthropic-skills:"

NEW_FILE_MODE = 0o600


def override_key(skill: str) -> str:
    prefix, name = "", skill
    if skill.startswith(SYNCED_PREFIX):
        prefix, name = SYNCED_PREFIX, skill[len(SYNCED_PREFIX):]
    if ":" in name:
        raise OverrideError(409, "plugin_managed", PLUGIN_NO_TOGGLE_REASON)
    reason = unsafe_name_reason(name)
    if reason is not None:
        raise OverrideError(400, "bad_skill", reason)
    return prefix + name


def _merge_override(data: Any, key: str, state: Optional[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("settings file is not a JSON object")
    block = data.get("skillOverrides")
    if block is not None and not isinstance(block, dict):
        raise ValueError("skillOverrides is not a JSON object")
    block = dict(block or {})
    if state is None:
        if key not in block:
            return None
        del block[key]
    else:
        if block.get(key) == state:
            return None
        block[key] = state
    merged = {k: v for k, v in data.items() if k != "skillOverrides"}
    if block:
        merged["skillOverrides"] = block
    return merged


def write_skill_override(
    settings_path: str, skill: str, state: Optional[str], *, backup: bool = True
) -> bool:
    if state is not None and state not in CLAUDE_STATES:
        raise OverrideError(400, "bad_state", f"state must be one of {', '.join(CLAUDE_STATES)} or null")
    key = override_key(skill)
    real = Path(os.path.realpath(settings_path))
    assert_test_write_allowed(real)
    mode = NEW_FILE_MODE
    try:
        stat = real.stat()
    except FileNotFoundError:
        if state is None:
            return False
        if not real.parent.is_dir():
            raise OverrideError(404, "settings_dir_missing", "the settings folder does not exist")
        config_writer.create_if_absent(real, {}, file_mode=NEW_FILE_MODE)
    else:
        if stat.st_size > MAX_SETTINGS_BYTES:
            raise OverrideError(409, "settings_unparseable", "the settings file is too large to edit safely")
        mode = stat.st_mode & 0o777
    try:
        outcome = config_writer.commit(
            real,
            lambda data: _merge_override(data, key, state),
            file_mode=mode,
            external_writer=True,
            backup=backup,
        )
    except ValueError as exc:
        logger.warning("skill_manager_settings_unparseable", path=str(real), error=type(exc).__name__)
        raise OverrideError(409, "settings_unparseable", "the settings file is not valid JSON") from exc
    except FileNotFoundError as exc:
        raise OverrideError(409, "settings_changed", "the settings file changed while it was being edited") from exc
    if outcome.status == config_writer.STALE_REVISION:
        raise OverrideError(409, "settings_changed", "the settings file changed while it was being edited")
    logger.info(
        "skill_manager_override_written",
        harness="claude",
        key=key,
        cleared=state is None,
        wrote=outcome.wrote,
    )
    return outcome.wrote
