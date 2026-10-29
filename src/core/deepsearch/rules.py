
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

import structlog

from src.core import config_writer
from src.core.deepsearch import constants as K

logger = structlog.get_logger()

Action = Union[str, int]

DEFAULT_RULES: Dict[str, Any] = {
    "max_message_chars": 20000,
    "strip_harness_wrappers": True,
    "sidechain": K.DROP,
    "compact_summary": K.DROP,
    "blocks": {"text": K.KEEP, "thinking": K.DROP, "tool_use": K.DROP, "tool_result": K.DROP, "image": K.DROP},
    "tool_use_fields": ["file_path", "path", "command", "pattern", "url", "description", "query"],
    "tools": {},
}

_TOP_KEYS = set(DEFAULT_RULES) | {"families"}
_FAMILIES = ("claude", "codex")


class RulesError(ValueError):
    pass


def _check_action(where: str, value: Any) -> None:
    if value in (K.KEEP, K.DROP):
        return
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= K.MAX_TRUNCATE_CHARS:
        return
    raise RulesError(f"{where}: must be 'keep', 'drop' or 1..{K.MAX_TRUNCATE_CHARS}")


def _check_block(where: str, block: Any, *, allow_families: bool) -> None:
    if not isinstance(block, dict):
        raise RulesError(f"{where}: must be an object")
    allowed = _TOP_KEYS if allow_families else set(DEFAULT_RULES)
    for key, value in block.items():
        if key not in allowed:
            raise RulesError(f"{where}.{key}: unknown rule")
        if key == "max_message_chars":
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= K.MAX_TRUNCATE_CHARS:
                raise RulesError(f"{where}.max_message_chars: 1..{K.MAX_TRUNCATE_CHARS}")
        elif key == "strip_harness_wrappers":
            if not isinstance(value, bool):
                raise RulesError(f"{where}.strip_harness_wrappers: must be true or false")
        elif key in ("sidechain", "compact_summary"):
            _check_action(f"{where}.{key}", value)
        elif key in ("blocks", "tools"):
            if not isinstance(value, dict):
                raise RulesError(f"{where}.{key}: must be an object")
            for name, action in value.items():
                if key == "blocks" and name not in DEFAULT_RULES["blocks"]:
                    raise RulesError(f"{where}.blocks.{name}: unknown block type")
                _check_action(f"{where}.{key}.{name}", action)
        elif key == "tool_use_fields":
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise RulesError(f"{where}.tool_use_fields: must be a list of names")
        elif key == "families":
            if not isinstance(value, dict):
                raise RulesError(f"{where}.families: must be an object")
            for family, sub in value.items():
                if family not in _FAMILIES:
                    raise RulesError(f"{where}.families.{family}: unknown family")
                _check_block(f"{where}.families.{family}", sub, allow_families=False)


def validate(overrides: Any) -> Dict[str, Any]:
    _check_block("search_filter", overrides, allow_families=True)
    return overrides


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key == "families":
            continue
        if key in ("blocks", "tools") and isinstance(value, dict):
            out[key] = {**out.get(key, {}), **value}
        else:
            out[key] = copy.deepcopy(value)
    return out


def effective(overrides: Optional[Dict[str, Any]], family: str) -> Dict[str, Any]:
    over = overrides or {}
    merged = _merge(DEFAULT_RULES, over)
    fam = (over.get("families") or {}).get(family)
    return _merge(merged, fam) if isinstance(fam, dict) else merged


def version_of(overrides: Optional[Dict[str, Any]], family: str) -> str:
    blob = json.dumps(effective(overrides, family), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[: K.VERSION_CHARS]


def default_config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def read_overrides(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = config_path or default_config_path()
    try:
        block = config_writer.read_config(path).get(K.CONFIG_BLOCK) or {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("search_filter_config_unreadable", path=str(path), error=str(exc))
        return {}
    raw = block.get(K.CONFIG_FIELD) if isinstance(block, dict) else None
    if raw is None:
        return {}
    try:
        return validate(raw)
    except RulesError as exc:
        logger.warning("search_filter_config_invalid", error=str(exc))
        return {}


def write_overrides(overrides: Dict[str, Any], config_path: Optional[Path] = None) -> Dict[str, Any]:
    validate(overrides)
    path = config_path or default_config_path()

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block = config.get(K.CONFIG_BLOCK)
        if block is not None and not isinstance(block, dict):
            raise RulesError(f"the stored {K.CONFIG_BLOCK} block is not an object")
        if (block or {}).get(K.CONFIG_FIELD) == overrides:
            return None
        merged = dict(config)
        merged[K.CONFIG_BLOCK] = {**(block or {}), K.CONFIG_FIELD: overrides}
        return merged

    config_writer.commit(path, mutate)
    logger.info("search_filter_set", versions={f: version_of(overrides, f) for f in _FAMILIES})
    return overrides


def describe(overrides: Dict[str, Any]) -> Dict[str, Any]:
    return {"defaults": copy.deepcopy(DEFAULT_RULES), "overrides": overrides,
            "effective": {f: effective(overrides, f) for f in _FAMILIES},
            "versions": {f: version_of(overrides, f) for f in _FAMILIES}}
