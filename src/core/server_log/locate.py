
from __future__ import annotations

import functools
from pathlib import Path
from typing import Optional, Tuple

import structlog

from src.core import product_identity

logger = structlog.get_logger()

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "server.log"
LAUNCHD_LOG_DIR_NAME = "cloude-code"
LAUNCHD_LOG_FILE_NAME = "launchd.log"
DEV_LOG_PARENT_NAMES = ("Carnivore", "dev")
LOG_FILE_ENV_SUFFIX = "LOG_FILE"


def _menubar_dir(name: str) -> Path:
    return Path.home() / "Library" / "Application Support" / name / LOG_DIR_NAME


def menubar_log_files() -> Tuple[Path, ...]:
    names = (product_identity.MENUBAR_STATE_DIR_NAME, *product_identity.LEGACY_MENUBAR_STATE_DIR_NAMES)
    return tuple(_menubar_dir(name) / LOG_FILE_NAME for name in names)


def allowed_log_files() -> Tuple[Path, ...]:
    launchd = Path.home() / "Library" / "Logs" / LAUNCHD_LOG_DIR_NAME / LAUNCHD_LOG_FILE_NAME
    return (*menubar_log_files(), launchd, dev_log_file())


def dev_log_file() -> Path:
    return Path.home().joinpath("Library", "Logs", *DEV_LOG_PARENT_NAMES, LOG_FILE_NAME)


def _dev_path_is_clean(path: Path) -> bool:
    for part in (path, *path.parents[: len(DEV_LOG_PARENT_NAMES)]):
        if part.is_symlink():
            return False
    return True


def validated_log_path(raw: object) -> Optional[Path]:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        return None
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        return None
    if path not in allowed_log_files():
        return None
    if path == dev_log_file() and not _dev_path_is_clean(path):
        logger.warning("server_log_dev_path_refused", reason="a link in the dev log path")
        return None
    return path


@functools.lru_cache(maxsize=1)
def own_log_path() -> Optional[Path]:
    raw = product_identity.env_value(LOG_FILE_ENV_SUFFIX)
    if raw is None:
        return None
    path = validated_log_path(raw)
    if path is None:
        logger.warning("server_log_env_path_refused", reason="not an allowed log file")
    return path


def default_log_path() -> Path:
    user_data = product_identity.resolve_named(
        Path.home() / "Library" / "Application Support",
        product_identity.MENUBAR_STATE_DIR_NAME,
        product_identity.LEGACY_MENUBAR_STATE_DIR_NAMES,
    ).path
    return user_data / LOG_DIR_NAME / LOG_FILE_NAME


def server_log_path() -> Path:
    return own_log_path() or default_log_path()

