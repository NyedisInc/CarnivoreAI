
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

import structlog

from src.models.catalog import DIGEST_RE, PUBLISHER_RE, SKILL_NAME_RE, VERSION_RE

logger = structlog.get_logger()

LOADOUT_SCHEMA = "carnivore.catalog.loadout/1"

MAX_MEMBERS = 64


@dataclass(frozen=True)
class LoadoutMember:

    item_id: str
    version: str
    digest: str


@dataclass(frozen=True)
class LoadoutManifest:

    name: str
    description: str | None
    members: Tuple[LoadoutMember, ...]


class LoadoutManifestInvalid(ValueError):

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _require_mapping(raw: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise LoadoutManifestInvalid(
            f"{what} is {type(raw).__name__}, not an object"
        )
    return raw


def _require_text(raw: Any, what: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise LoadoutManifestInvalid(f"{what} is missing or is not a string")
    return raw.strip()


def _member_id_shape(item_id: str) -> None:
    parts = item_id.split("/")
    if len(parts) != 2:
        raise LoadoutManifestInvalid(
            f"member id {item_id!r} is not '<publisher>/<name>'"
        )
    publisher, name = parts
    if not PUBLISHER_RE.fullmatch(publisher):
        raise LoadoutManifestInvalid(
            f"member id {item_id!r} has a publisher that is not a publisher"
        )
    if not SKILL_NAME_RE.fullmatch(name):
        raise LoadoutManifestInvalid(
            f"member id {item_id!r} has a name that is not a name"
        )


def _one_member(raw: Any, index: int) -> LoadoutMember:
    entry = _require_mapping(raw, f"members[{index}]")
    item_id = _require_text(entry.get("id"), f"members[{index}].id")
    _member_id_shape(item_id)

    version = _require_text(entry.get("version"), f"members[{index}].version")
    if not VERSION_RE.fullmatch(version):
        raise LoadoutManifestInvalid(
            f"members[{index}].version {version!r} is not a version"
        )

    digest = _require_text(entry.get("digest"), f"members[{index}].digest")
    if not DIGEST_RE.fullmatch(digest):
        raise LoadoutManifestInvalid(
            f"members[{index}].digest is not 64 lowercase hex characters"
        )

    return LoadoutMember(item_id=item_id, version=version, digest=digest)


def parse_loadout_manifest(text: str, *, own_id: str | None = None) -> LoadoutManifest:
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LoadoutManifestInvalid(f"loadout.json is not JSON: {exc}") from exc

    document = _require_mapping(raw, "loadout.json")

    schema = document.get("schema")
    if schema != LOADOUT_SCHEMA:
        raise LoadoutManifestInvalid(
            f"loadout.json announces schema {schema!r}; this version reads "
            f"{LOADOUT_SCHEMA!r} only"
        )

    name = _require_text(document.get("name"), "name")

    raw_description = document.get("description")
    description = (
        raw_description.strip()
        if isinstance(raw_description, str) and raw_description.strip()
        else None
    )

    raw_members = document.get("members")
    if not isinstance(raw_members, Sequence) or isinstance(raw_members, (str, bytes)):
        raise LoadoutManifestInvalid("members is missing or is not a list")
    if not raw_members:
        raise LoadoutManifestInvalid(
            "members is empty; a loadout that lists nothing installs "
            "nothing and there is no honest way to report that as a set"
        )
    if len(raw_members) > MAX_MEMBERS:
        raise LoadoutManifestInvalid(
            f"members lists {len(raw_members)} items, over the bound of "
            f"{MAX_MEMBERS}"
        )

    members: list[LoadoutMember] = []
    seen: set[str] = set()
    for position, entry in enumerate(raw_members):
        member = _one_member(entry, position)
        if member.item_id in seen:
            raise LoadoutManifestInvalid(
                f"members lists {member.item_id!r} more than once"
            )
        if own_id is not None and member.item_id == own_id:
            raise LoadoutManifestInvalid(
                f"members lists the loadout itself ({member.item_id!r})"
            )
        seen.add(member.item_id)
        members.append(member)

    logger.debug(
        "loadout_manifest_parsed", name=name, members=len(members)
    )
    return LoadoutManifest(
        name=name, description=description, members=tuple(members)
    )


def read_loadout_manifest(
    directory: Path, *, own_id: str | None = None
) -> LoadoutManifest:
    source = directory / "loadout.json"
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LoadoutManifestInvalid(
            f"loadout.json could not be read: {exc}"
        ) from exc
    return parse_loadout_manifest(text, own_id=own_id)
