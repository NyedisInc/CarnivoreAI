
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import structlog

from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

SIDECAR_NAME = ".carnivore-skill.json"

REQUIRED_FIELDS: tuple[str, ...] = (
    "publisher",
    "name",
    "version",
    "digest",
    "source_index_url",
    "installed_at",
)


@dataclass(frozen=True)
class SkillRecord:

    publisher: str
    name: str
    version: str
    digest: str
    source_index_url: str
    installed_at: str


def sidecar_path(directory: Path) -> Path:
    return directory / SIDECAR_NAME


def write_sidecar(directory: Path, record: SkillRecord) -> Path:
    destination = sidecar_path(directory)
    assert_test_write_allowed(destination)
    destination.write_text(
        json.dumps(asdict(record), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "skill_sidecar_written",
        directory=str(directory),
        publisher=record.publisher,
        name=record.name,
        version=record.version,
    )
    return destination


def read_sidecar(directory: Path) -> SkillRecord | None:
    source = sidecar_path(directory)
    try:
        raw = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "skill_sidecar_unreadable", path=str(source), error=str(exc)
        )
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "skill_sidecar_malformed", path=str(source), error=str(exc)
        )
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "skill_sidecar_malformed",
            path=str(source),
            error=f"top level is {type(parsed).__name__}, not an object",
        )
        return None

    missing = [field for field in REQUIRED_FIELDS if field not in parsed]
    if missing:
        logger.warning(
            "skill_sidecar_malformed",
            path=str(source),
            error=f"missing required fields: {sorted(missing)}",
        )
        return None

    values = {field: parsed[field] for field in REQUIRED_FIELDS}
    wrong_type = sorted(k for k, v in values.items() if not isinstance(v, str))
    if wrong_type:
        logger.warning(
            "skill_sidecar_malformed",
            path=str(source),
            error=f"non-string values for: {wrong_type}",
        )
        return None

    return SkillRecord(**values)
