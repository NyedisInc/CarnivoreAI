"""What a kind's MANIFEST is, beyond its name, as two more tables.

**QUESTION 1: IS THE MANIFEST THE THING IT CLAIMS TO BE.** The archive
validator checks that a folder CARRIES its manifest, which is a check
about a path and is therefore kind-independent, exactly like every other
rule in that file. Presence is not validity. A ``theme.json`` that is not
JSON, or whose ``id`` disagrees with the folder it will be installed
into, passes a presence check and then fails at
``themes_routes._load_manifest``, which skips it with a warning. The
result is an item that is INSTALLED AND INVISIBLE: bytes on disk, a
ledger row, an update badge, and nothing in the picker. That is worse
than a refusal, because a refusal names the problem at the moment
somebody can still act on it. So a kind whose manifest has a STRUCTURE
gets that structure checked before the copy lands.

A skill's ``SKILL.md`` is prose with optional front matter and has no
structure this layer may insist on: front matter is advisory, the
previewer warns about unknown keys, and a skill with none is legal.
``SHAPE_TEXT`` says exactly that, and it is a declaration rather than an
omission - a future kind that forgets to declare anything raises instead
of being waved through, which is the rule :mod:`kinds` already sets.

**QUESTION 2: DOES THIS ITEM CARRY CODE.** The catalog counts executable
content by the POSIX owner-execute bit and by the ``scripts/`` folder,
and for a skill that is the whole answer: a skill's code is run by a
shell, and a shell needs the bit.

So script-bearing is kind-driven too: for a theme, a ``theme.json`` that
DECLARES an ``effects`` entry makes the folder script-bearing whatever
the mode bits say. It is read from the manifest rather than from a
filename, because the manifest is what the client resolves the script
through, and a rule that guessed ``effects.js`` would miss a theme that
named its script something else.

**BOTH ANSWERS FAIL TOWARDS THE REFUSAL.** A manifest that cannot be read
is not a manifest that is fine: :func:`check_manifest` names the reason
and :func:`declares_script` answers True, because "I could not tell
whether this ships code" must never be spent as "it does not".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

import structlog

from src.core.skills import kinds
from src.core.skills.plugin_safe_subset import plugin_declares_code

logger = structlog.get_logger()

SHAPE_TEXT = "text"

SHAPE_JSON = "json"

MANIFEST_SHAPE_FOR: Mapping[str, str] = {
    kinds.KIND_SKILL: SHAPE_TEXT,
    kinds.KIND_THEME: SHAPE_JSON,
    kinds.KIND_PLUGIN: SHAPE_JSON,
    kinds.KIND_LOADOUT: SHAPE_JSON,
    kinds.KIND_MOD: SHAPE_JSON,
    kinds.KIND_CPLUG: SHAPE_JSON,
}

IDENTITY_KEY_FOR: Mapping[str, Optional[str]] = {
    kinds.KIND_SKILL: None,
    kinds.KIND_THEME: "id",
    kinds.KIND_PLUGIN: None,
    kinds.KIND_LOADOUT: None,
    kinds.KIND_MOD: None,
    kinds.KIND_CPLUG: None,
}

SCRIPT_KEY_FOR: Mapping[str, Optional[str]] = {
    kinds.KIND_SKILL: None,
    kinds.KIND_THEME: "effects",
    kinds.KIND_PLUGIN: None,
    kinds.KIND_LOADOUT: None,
    kinds.KIND_MOD: None,
    kinds.KIND_CPLUG: None,
}

MAX_MANIFEST_BYTES = 1024 * 1024


def manifest_shape(kind: str) -> str:
    if kind not in MANIFEST_SHAPE_FOR:
        raise ValueError(
            f"unknown install kind {kind!r}; known kinds are "
            f"{sorted(MANIFEST_SHAPE_FOR)}"
        )
    return MANIFEST_SHAPE_FOR[kind]


def identity_key(kind: str) -> Optional[str]:
    if kind not in IDENTITY_KEY_FOR:
        raise ValueError(
            f"unknown install kind {kind!r}; known kinds are "
            f"{sorted(IDENTITY_KEY_FOR)}"
        )
    return IDENTITY_KEY_FOR[kind]


def script_key(kind: str) -> Optional[str]:
    if kind not in SCRIPT_KEY_FOR:
        raise ValueError(
            f"unknown install kind {kind!r}; known kinds are "
            f"{sorted(SCRIPT_KEY_FOR)}"
        )
    return SCRIPT_KEY_FOR[kind]


def _read_manifest_object(kind: str, folder: Path) -> tuple[Optional[dict], Optional[str]]:
    name = kinds.manifest_name(kind)
    path = folder / name
    try:
        if not path.is_file():
            return None, f"{name} is missing from the folder"
        size = path.stat().st_size
        if size > MAX_MANIFEST_BYTES:
            return None, f"{name} is larger than {MAX_MANIFEST_BYTES} bytes"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{name} could not be read: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"{name} is not valid JSON: {exc}"
    if not isinstance(raw, dict):
        return None, f"{name} is not a JSON object"
    return raw, None


def check_manifest(kind: str, folder: Path, *, expected_id: str) -> Optional[str]:
    if manifest_shape(kind) == SHAPE_TEXT:
        return None

    raw, refusal = _read_manifest_object(kind, folder)
    if refusal is not None:
        return refusal

    key = identity_key(kind)
    if key is None:
        return None

    declared = raw.get(key)
    if declared != expected_id:
        return (
            f"{kinds.manifest_name(kind)} declares {key} {declared!r} but the "
            f"folder is installed as {expected_id!r}; the two must match or "
            f"the {kind} is installed and never listed"
        )
    return None


def declares_script(kind: str, folder: Path) -> bool:
    """Whether this folder's MANIFEST says it ships executable content.

      A MANIFEST THAT CANNOT BE READ ANSWERS TRUE. Not knowing whether
      something ships code is not evidence that it does not, and the only
      consumer of this answer is a guard that refuses when it is True; a
      False on a failed read would spend the refusal it could not earn.
    Inputs: kind (str). folder (Path) - a staged or installed folder.
    Output: bool.
    Raises: ValueError on a kind this version does not know.
    Example: declares_script("theme", staged)
    """
    key = script_key(kind)
    if key is None and kind != kinds.KIND_PLUGIN:
        return False

    raw, refusal = _read_manifest_object(kind, folder)
    if refusal is not None:
        logger.warning(
            "manifest_script_declaration_unreadable",
            kind=kind,
            folder=str(folder),
            reason=refusal,
            outcome="treated as script bearing",
        )
        return True

    if kind == kinds.KIND_PLUGIN:
        return plugin_declares_code(raw, folder)
    declared = raw.get(key)
    return isinstance(declared, str) and bool(declared.strip())
