
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.models.catalog import RESERVED_SKILL_NAMES, SKILL_NAME_RE

__all__ = [
    "DEFAULT_VERSION",
    "MANIFEST_NAME",
    "MAX_DESCRIPTION_CHARS",
    "MAX_FILE_BYTES",
    "MAX_MEMBERS",
    "MAX_PATH_LENGTH",
    "MAX_SUBMISSION_BYTES",
    "RESERVED_SKILL_NAMES",
    "SKILL_NAME_RE",
    "Refusal",
    "BODY_TOO_LARGE",
    "NAME_RESERVED",
    "SCRIPTS_NOT_SUPPORTED",
    "SUBMISSION_INVALID",
    "frontmatter",
    "refuse_manifest",
    "refuse_member_path",
    "refuse_name",
]

MAX_SUBMISSION_BYTES = 1024 * 1024

MAX_MEMBERS = 2000

MAX_FILE_BYTES = 256 * 1024

MAX_PATH_LENGTH = 200

MAX_DESCRIPTION_CHARS = 1024

MANIFEST_NAME = "SKILL.md"

DEFAULT_VERSION = "1.0.0"

SUBMISSION_INVALID = "submission_invalid"
NAME_RESERVED = "name_reserved"
SCRIPTS_NOT_SUPPORTED = "scripts_not_supported"
BODY_TOO_LARGE = "body_too_large"

_FRONTMATTER_RE = re.compile(r"^---[^\S\n]*\n(.*?\n)---[^\S\n]*\n", re.DOTALL)

_SCRIPTS_DIR = "scripts"


@dataclass(frozen=True)
class Refusal:

    code: str
    detail: str
    path: Optional[str] = None


def frontmatter(text: str) -> Dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line[:1].isspace() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        fields[key.strip()] = value.strip().strip("'\"")
    return fields


def refuse_name(name: str) -> Optional[Refusal]:
    if not name or not SKILL_NAME_RE.match(name):
        return Refusal(
            SUBMISSION_INVALID,
            f"a skill name must match {SKILL_NAME_RE.pattern}",
            name or None,
        )
    if name.lower() in RESERVED_SKILL_NAMES:
        return Refusal(
            NAME_RESERVED, "a harness already ships a skill with that name", name
        )
    return None


def refuse_member_path(path: str, seen: Dict[str, str]) -> Optional[Refusal]:
    if not path:
        return Refusal(SUBMISSION_INVALID, "every file needs a path")
    if len(path) > MAX_PATH_LENGTH:
        return Refusal(
            SUBMISSION_INVALID,
            f"a path is longer than {MAX_PATH_LENGTH} characters",
            path,
        )
    if not path.isascii():
        return Refusal(SUBMISSION_INVALID, "a path is not ascii", path)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        return Refusal(SUBMISSION_INVALID, "a path carries a control character", path)
    if "\\" in path:
        return Refusal(SUBMISSION_INVALID, "a path carries a backslash", path)
    if path.startswith("/"):
        return Refusal(SUBMISSION_INVALID, "a path is absolute", path)
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        return Refusal(SUBMISSION_INVALID, "a path is not a plain relative path", path)
    folded = path.lower()
    if folded in seen:
        return Refusal(
            SUBMISSION_INVALID, f"two files share the path {seen[folded]!r}", path
        )
    seen[folded] = path
    return None


def refuses_for_scripts(paths: List[str]) -> Optional[Refusal]:
    for path in paths:
        if path.split("/", 1)[0] == _SCRIPTS_DIR:
            return Refusal(
                SCRIPTS_NOT_SUPPORTED,
                "this catalog does not publish executable content",
                path,
            )
    return None


def refuse_manifest(name: str, manifest_text: Optional[str]) -> List[Refusal]:
    if manifest_text is None:
        return [
            Refusal(
                SUBMISSION_INVALID,
                f"the folder carries no readable {MANIFEST_NAME}",
                MANIFEST_NAME,
            )
        ]
    fields = frontmatter(manifest_text)
    if not fields:
        return [
            Refusal(
                SUBMISSION_INVALID,
                f"{MANIFEST_NAME} carries no yaml front matter block",
                MANIFEST_NAME,
            )
        ]
    found: List[Refusal] = []
    declared = fields.get("name")
    if declared != name:
        found.append(
            Refusal(
                SUBMISSION_INVALID,
                f"{MANIFEST_NAME} front matter names {declared!r}, "
                f"the folder is {name!r}",
                MANIFEST_NAME,
            )
        )
    description = fields.get("description", "")
    if not description:
        found.append(
            Refusal(
                SUBMISSION_INVALID,
                f"{MANIFEST_NAME} front matter carries no description",
                MANIFEST_NAME,
            )
        )
    elif len(description) > MAX_DESCRIPTION_CHARS:
        found.append(
            Refusal(
                SUBMISSION_INVALID,
                f"the description is longer than {MAX_DESCRIPTION_CHARS} characters",
                MANIFEST_NAME,
            )
        )
    return found
