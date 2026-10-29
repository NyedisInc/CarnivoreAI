from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import structlog

from src.core import config_files
from src.core.config_files import ConfigFileError

logger = structlog.get_logger()

CONFIRM_EXECUTABLE = "executable"
CONFIRM_SENSITIVE = "sensitive"


class ConfirmationRequiredError(ConfigFileError):

    def __init__(self, message: str, acknowledge: str) -> None:
        super().__init__(message)
        self.acknowledge = acknowledge


def create_file(
    root_id: str,
    rel_path: str,
    content: str,
    project_path: Optional[str],
    acknowledge_executable: bool = False,
    acknowledge_sensitive: bool = False,
) -> dict:
    if not (rel_path or "").strip().strip("/"):
        raise ConfigFileError("a file name is required")

    path = config_files.resolve_safe_path(root_id, rel_path, project_path)
    roots = config_files.resolve_roots(project_path)
    root = roots[root_id]

    if path == root:
        raise ConfigFileError("a file name is required")
    if path.exists() or path.is_symlink():
        raise ConfigFileError(f"'{rel_path}' already exists - open it instead of creating it")

    parent = path.parent
    if not parent.is_dir():
        raise ConfigFileError(
            f"'{_rel(root, parent)}' does not exist - create the file in an "
            "existing directory (this editor does not make directories)"
        )

    is_executable, is_sensitive, read_only = config_files.classify(root, path)
    if read_only:
        raise ConfigFileError("this location is under a read-only root (plugins/)")
    if is_executable and not acknowledge_executable:
        raise ConfirmationRequiredError(
            "a file here is executed automatically by claude code - "
            "create refused without explicit confirmation",
            CONFIRM_EXECUTABLE,
        )
    if is_sensitive and not acknowledge_sensitive:
        raise ConfirmationRequiredError(
            "this name looks like credentials/a secret/a private key - "
            "create refused without explicit confirmation",
            CONFIRM_SENSITIVE,
        )

    if path.suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ConfigFileError(f"invalid json: {exc.msg} (line {exc.lineno}, col {exc.colno})")

    try:
        config_files.atomic_write(path, content)
    except OSError as exc:
        logger.warning("config_files_create_failed", root=root_id, rel_path=rel_path, error=str(exc))
        raise ConfigFileError(f"could not create the file: {exc.strerror or exc}")

    logger.info(
        "config_files_create",
        root=root_id,
        rel_path=rel_path,
        is_executable=is_executable,
        is_sensitive=is_sensitive,
        bytes=len(content),
    )
    return {
        "created": True,
        "rel_path": rel_path.strip().strip("/"),
        "is_executable": is_executable,
        "is_sensitive": is_sensitive,
    }


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return path.name
