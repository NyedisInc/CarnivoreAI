"""What each catalog KIND is made of, as one table nothing may bypass.

THE CATALOG CORE IS KIND-AGNOSTIC AND THIS IS THE ONE PLACE THAT IS NOT.
Trust, signing, revocation, the folder digest, the extractor's safety
rules, the ledger, the journal and the trash are identical for every
kind: they are about BYTES and about PATHS, and a theme's bytes are not
special. What differs between a skill and a theme is three facts, and all
three live here so that adding a third kind is an entry in three dicts
rather than a hunt through nine modules.

THE THREE FACTS, AND WHY EACH ONE IS A FACT AND NOT A CONVENTION.

1. **The manifest.** The file the consuming program keys on. Claude and
   Codex load a skill folder because it holds ``SKILL.md``; this app
   loads a theme folder because it holds ``theme.json``
   (``src/api/themes_routes.py::_load_manifest``). A folder installed
   without its manifest is installed and INVISIBLE, which is worse than a
   refusal, so the manifest is also the last gate before a copy lands.

2. **The archive folder.** The segment under the catalog repository's
   root that a kind's folders live in. The extractor keeps
   ``<folder>/<publisher>/<name>/**`` and drops everything else, so this
   string decides which members of somebody else's repository tarball are
   even considered. A theme published under ``themes/`` and extracted as
   though it were under ``skills/`` would simply yield an empty folder,
   which is a confusing refusal rather than an honest one.

3. **The scopes.** A skill is a per-harness artifact and can be installed
   for one project or for the whole machine. A THEME IS A PER-APP
   RESOURCE: this app reads themes from exactly two directories and
   neither of them is inside a project. The project-level equivalent
   already exists and this catalog does not own it - it is the
   ``<working_dir>/.cc.theme`` dotfile, which names a theme rather than
   containing one. So ``theme`` declares GLOBAL only, and a project-scope
   install of one is refused in the open rather than written somewhere
   plausible.

**AN UNKNOWN KIND RAISES; IT NEVER FALLS BACK.** Every lookup here is a
``ValueError`` on a kind this version does not know, for the reason the
``InstallRoots`` port already states: a default would write an item of an
unrecognised shape into whichever directory happened to be first. The
client refuses an unknown kind at parse time
(``src/models/catalog.py::CatalogItem.kind``), so reaching one of these
with a bad kind is a programming error, and a programming error that
answers plausibly is the expensive kind.
"""

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
    """The ``<folder>/<publisher>/<name>`` an item's files live under.

    Description: with no ``src_path`` this is the kind's current folder.
      With the signed ``version.src.path`` it must be exactly
      ``<allowed folder for that kind>/<publisher>/<name>``, else refused.
    Inputs: kind, publisher, name (str); src_path (str | None).
    Output: str, no trailing slash.
    Raises: ValueError on an unknown kind or a src_path that is not allowed.
    Example: archive_root("cplug", "h", "n", "cplugs/h/n")  # 'cplugs/h/n'
    """
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
