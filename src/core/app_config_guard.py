
from __future__ import annotations

import os
from pathlib import Path

import structlog

logger = structlog.get_logger()

APP_CONFIG_PROTECTED = "app_config_protected"


def app_config_path() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.auth_config_file).expanduser()


def is_app_config(candidate: Path) -> bool:
    app_config = app_config_path()
    try:
        return os.path.samefile(candidate, app_config)
    except OSError:
        pass

    candidate_real = os.path.realpath(candidate)
    app_real = os.path.realpath(app_config)
    same_parent = os.path.normcase(os.path.dirname(candidate_real)) == os.path.normcase(
        os.path.dirname(app_real)
    )
    same_leaf = (
        os.path.normcase(os.path.basename(candidate_real)).casefold()
        == os.path.normcase(os.path.basename(app_real)).casefold()
    )
    return same_parent and same_leaf


class AppConfigProtectedError(ValueError):
    pass


def refuse_if_app_config(candidate: Path, *, root_id: str, rel_path: str) -> None:
    if not is_app_config(candidate):
        return
    logger.warning(
        "config_files_write_refused_app_config", root=root_id, rel_path=rel_path
    )
    raise AppConfigProtectedError(
        "this is the cloude server's own config.json - edit it in "
        "settings, not in the file browser"
    )
