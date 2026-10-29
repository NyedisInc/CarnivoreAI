
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from pydantic import ValidationError

from src.core.blueprints_store import serialize
from src.core.json_artifact import atomic_write_json
from src.models.blueprints import BlueprintSpec

SWARM_DIR = ".carnivore"
SWARM_FILE = "swarm.json"

MAX_FILE_BYTES = 256 * 1024

MAX_ERRORS_SHOWN = 5


class SwarmFileError(ValueError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def swarm_path(project_root: str) -> Path:
    directory = Path(project_root) / SWARM_DIR
    if os.path.islink(directory) or (os.path.lexists(directory) and not directory.is_dir()):
        raise SwarmFileError("swarm_path_unsafe",
                             f"{directory} is a link or not a directory, so it is not used")
    target = directory / SWARM_FILE
    if os.path.islink(target):
        raise SwarmFileError("swarm_path_unsafe", f"{target} is a link, so it is not used")
    return target


def write_swarm(project_root: str, spec: BlueprintSpec) -> Path:
    target = swarm_path(project_root)
    payload = json.loads(serialize(spec))
    target.parent.mkdir(exist_ok=True)
    if os.path.realpath(target.parent) != str(target.parent):
        raise SwarmFileError("swarm_path_unsafe", f"{target.parent} does not resolve to itself")
    if not atomic_write_json(target, payload, log_event="blueprint_export_write_failed"):
        raise SwarmFileError("swarm_write_failed", f"{target} could not be written")
    return target


def _errors(exc: ValidationError) -> str:
    parts: List[str] = []
    for error in exc.errors(include_url=False, include_input=False)[:MAX_ERRORS_SHOWN]:
        where = ".".join(str(p) for p in error.get("loc", ())) or "(top level)"
        parts.append(f"{where}: {error.get('msg')}")
    return "; ".join(parts)


def read_swarm(project_root: str) -> BlueprintSpec:
    target = swarm_path(project_root)
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise SwarmFileError("swarm_file_missing", f"{target} does not exist") from None
    except OSError as exc:
        raise SwarmFileError("swarm_path_unsafe", f"{target} cannot be opened: {exc.strerror}") from None
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise SwarmFileError("swarm_file_invalid", f"{target} is larger than {MAX_FILE_BYTES} bytes")
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise SwarmFileError("swarm_file_invalid", f"{target} is not UTF-8 text") from None
    except json.JSONDecodeError as exc:
        raise SwarmFileError("swarm_file_invalid",
                             f"{target} is not valid JSON (line {exc.lineno}, column {exc.colno}: "
                             f"{exc.msg})") from None
    if not isinstance(document, dict):
        raise SwarmFileError("swarm_file_invalid", f"{target} does not hold a JSON object")
    try:
        return BlueprintSpec.model_validate(document)
    except ValidationError as exc:
        raise SwarmFileError("swarm_file_invalid",
                             f"{target} is not a valid blueprint: {_errors(exc)}") from None
