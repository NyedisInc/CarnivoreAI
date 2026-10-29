
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.config_files_io import atomic_write
from src.core.time_machine import constants as C

logger = structlog.get_logger()
_GB = 1024 ** 3


def tree_root(state_dir: Path) -> Path:
    return Path(state_dir) / C.TREE_DIR_NAME


def _env_cap_bytes() -> Optional[int]:
    env = os.environ.get(C.CAP_ENV_VAR)
    if not env:
        return None
    try:
        if float(env) > 0:
            return int(float(env) * _GB)
    except ValueError:
        logger.warning("time_machine_cap_env_invalid", value=env)
    return None


def cap_env_locked() -> bool:
    return _env_cap_bytes() is not None


def read_limits(state_dir: Path) -> Dict[str, Any]:
    path = tree_root(state_dir) / C.LIMITS_FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("time_machine_limits_unreadable", path=str(path), error=str(exc))
        return {}
    return data if isinstance(data, dict) else {}


def cap_bytes(state_dir: Path) -> int:
    env = _env_cap_bytes()
    if env is not None:
        return env
    try:
        value = float(read_limits(state_dir).get("cap_gb"))
        if value > 0:
            return int(value * _GB)
    except (ValueError, TypeError):
        pass
    return C.DEFAULT_CAP_BYTES


def _write(state_dir: Path, changes: Dict[str, Any]) -> None:
    root = tree_root(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    atomic_write(root / C.LIMITS_FILE_NAME, json.dumps({**read_limits(state_dir), **changes}, indent=2, sort_keys=True))


def write_changes(state_dir: Path, changes: Dict[str, Any]) -> None:
    _write(state_dir, changes)


def set_cap_gb(state_dir: Path, cap_gb: float) -> int:
    if not cap_gb or cap_gb <= 0:
        raise ValueError("cap_gb must be positive")
    _write(state_dir, {"cap_gb": float(cap_gb)})
    return int(cap_gb * _GB)


def summary_method(state_dir: Path) -> str:
    value = read_limits(state_dir).get("summary_method")
    return value if value in C.SUMMARY_METHODS else C.DEFAULT_SUMMARY_METHOD


def summary_model(state_dir: Path) -> str:
    value = read_limits(state_dir).get("summary_model")
    return value.strip() if isinstance(value, str) and value.strip() else C.DEFAULT_SUMMARY_MODEL


def set_summary(state_dir: Path, *, method: Optional[str] = None, model: Optional[str] = None) -> None:
    changes: Dict[str, Any] = {}
    if method is not None:
        if method not in C.SUMMARY_METHODS:
            raise ValueError(f"unknown summary method {method!r}")
        changes["summary_method"] = method
    if model is not None:
        cleaned = model.strip()
        if not cleaned or len(cleaned) > C.SUMMARY_MODEL_MAX_CHARS or any(c.isspace() for c in cleaned):
            raise ValueError("summary_model must be a single model id")
        changes["summary_model"] = cleaned
    if changes:
        _write(state_dir, changes)
