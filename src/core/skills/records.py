"""The ``.carnivore-skill.json`` sidecar: what an installed folder says it is.

An installed skill folder is otherwise indistinguishable from one the user
wrote by hand, and the difference decides whether this app may replace it.
The sidecar is that difference: it is written INSIDE the installed folder,
beside ``SKILL.md``, and it names the publisher, the version, the digest
that was verified and the index it came from.

WHY INSIDE THE FOLDER AND NOT ONLY IN THE DATABASE. The database is the
ledger and stays the authority on what THIS app installed. The sidecar
answers a question the ledger cannot: a folder copied, restored from a
backup, or synced onto a second machine still carries its own provenance.
A ledger row without a folder is a stale row; a folder without a ledger row
is, with the sidecar, still identifiable.

WHY IT DOES NOT SHOW UP AS A SKILL. Both scanners key on a MANIFEST FILE,
not on the folder: ``slash_command_discovery._scan_skill_dirs`` globs for
``SKILL.md`` and reports one command per directory that holds one, and
Codex does the same. A ``.json`` file matches nothing, so adding this
sidecar adds no entry to any palette, in either harness. It is also
dot-prefixed, so the dot-directory skip added for ``.system`` would hide it
even if the rule ever changed to look at names.

WHY A MALFORMED SIDECAR ANSWERS None AND NEVER RAISES. This file is read
on the listing path, next to a folder the user can edit by hand. A parse
failure means "this folder does not carry provenance this app can read",
which is the SAME position as a folder with no sidecar at all, and both of
those are things the caller has to handle anyway. An exception here would
turn one hand-edited file into a failed listing for every installed skill.
The failure is LOGGED, so it is a visible absence rather than a silent one.
"""

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
    """Write the sidecar into an installed folder.

    Description: a plain whole-file write, not the atomic replace the
      config writer uses, because this file is written exactly once,
      inside a folder that does not exist yet from anyone else's point of
      view, immediately before that folder is renamed into place. There is
      no concurrent reader to tear.
    Inputs: directory (Path) - the installed folder. record (SkillRecord).
    Output: Path - the file that was written.
    Raises: OutsideTempWriteError when a test run aims this at a real path.
    Example: write_sidecar(staged, record).name  # '.carnivore-skill.json'
    """
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
