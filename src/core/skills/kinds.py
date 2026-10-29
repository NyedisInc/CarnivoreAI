
from __future__ import annotations

from typing import Mapping, Tuple

KIND_SKILL = "skill"

KIND_THEME = "theme"

KIND_PLUGIN = "plugin"

KIND_LOADOUT = "loadout"

KIND_MOD = "mod"

KIND_CPLUG = "cplug"


KINDS: Tuple[str, ...] = (
    KIND_SKILL,
    KIND_THEME,
    KIND_PLUGIN,
    KIND_LOADOUT,
    KIND_MOD,
    KIND_CPLUG,
)

MANIFEST_FOR: Mapping[str, str] = {
    KIND_SKILL: "SKILL.md",
    KIND_THEME: "theme.json",
    KIND_PLUGIN: ".claude-plugin/plugin.json",
    KIND_LOADOUT: "loadout.json",
    KIND_MOD: ".claude-plugin/plugin.json",
    KIND_CPLUG: "cplug.json",
}

ARCHIVE_FOLDER_FOR: Mapping[str, str] = {
    KIND_SKILL: "skills",
    KIND_THEME: "themes",
    KIND_PLUGIN: "plugins",
    KIND_LOADOUT: "loadouts",
    KIND_MOD: "mods",
    KIND_CPLUG: "cplugs",
}

ARCHIVE_FOLDERS_FOR: Mapping[str, Tuple[str, ...]] = {
    **{kind: (folder,) for kind, folder in ARCHIVE_FOLDER_FOR.items()},
    KIND_CPLUG: ("plugins", "cplugs"),
}

SCOPES_FOR: Mapping[str, Tuple[str, ...]] = {
    KIND_SKILL: ("global", "project"),
    KIND_THEME: ("global",),
    KIND_PLUGIN: ("global", "project"),
    KIND_LOADOUT: ("global",),
    KIND_MOD: ("global",),
    KIND_CPLUG: ("global",),
}


def _known(kind: str, table: Mapping[str, object]) -> None:
    if kind not in table:
        raise ValueError(
            f"unknown install kind {kind!r}; known kinds are {sorted(table)}"
        )


def manifest_name(kind: str) -> str:
    _known(kind, MANIFEST_FOR)
    return MANIFEST_FOR[kind]


def archive_folder(kind: str) -> str:
    _known(kind, ARCHIVE_FOLDER_FOR)
    return ARCHIVE_FOLDER_FOR[kind]


def archive_root(
    kind: str, publisher: str, name: str, src_path: str | None = None
) -> str:
    _known(kind, ARCHIVE_FOLDERS_FOR)
    folders = ARCHIVE_FOLDERS_FOR[kind]
    if src_path is None:
        return f"{ARCHIVE_FOLDER_FOR[kind]}/{publisher}/{name}"
    for folder in folders:
        if src_path == f"{folder}/{publisher}/{name}":
            return src_path
    raise ValueError(
        f"src.path {src_path!r} is not <{'|'.join(folders)}>/{publisher}/{name} "
        f"for a {kind}"
    )


def scopes_for(kind: str) -> Tuple[str, ...]:
    _known(kind, SCOPES_FOR)
    return SCOPES_FOR[kind]


def scope_supported(kind: str, scope: str) -> bool:
    return scope in scopes_for(kind)
