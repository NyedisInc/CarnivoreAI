
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.claude_project_dirs import path_spellings
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.deepsearch.constants import BACKUP_COPY_DIR
from src.core.inventory import registry
from src.core.inventory.claim_rows import open_side
from src.core.inventory.claude_folders import conversation_form, notes_entries, project_folders
from src.core.inventory.file_trace import measured_artifact
from src.core.inventory.identity import SAFE_CONVERSATION
from src.core.inventory.locations import Locations
from src.core.inventory.model import (KIND_DIR, MAIN_STORE, REPORT, ROLE_KEY, ROLE_PATH, Artifact, FieldRef, ProjectIdentity,
                                      SessionIdentity)
from src.core.inventory.scope import CONVERSATIONS, Scope
from src.core.inventory.vault_claims import vault_manifests
from src.core.sessions import theme_dotfile
from src.core.time_machine.limits import tree_root
from src.core.work import storage as work_storage
from src.core.work import tables as work_tables

logger = structlog.get_logger()

STORE_POINTS = "time-machine"
STORE_BACKUP_COPIES = BACKUP_COPY_DIR
STORE_PIPE = "tmux-pipe-log"
STORE_TASK_FILES = "task-manager-files"
STORE_DESK = "swarm-desk"
STORE_SWARM_SETTINGS = "swarm-settings"
STORE_SWARM_HOOKS = "swarm-hooks"
STORE_THEME_DOTFILE = "cc-theme"
STORE_MEMORY = "claude-memory"
STORE_ORPHANS = "claude-orphans"
STORE_FOLDER = "project-folder"

SWARM_DESK_DIR = ("swarm", "desk")
SWARM_SETTINGS_DIR = ("swarm", "settings")
SWARM_HOOKS_DIR = ("swarm", "hooks")
TASK_FILES_DIR = "files"
_CONVERSATION_ENTRY = re.compile(r"^(?P<id>[0-9A-Za-z][0-9A-Za-z-]{7,63})(\.jsonl)?$")

_POINT_REWRITE = (FieldRef("<point>/meta.json#working_dir", ROLE_PATH), FieldRef("<point>/meta.json#transcript.source_path", ROLE_PATH),
                  FieldRef("<point>/meta.json#project", ROLE_KEY), FieldRef("<point>/meta.json#conversation_id", ROLE_KEY))
_COPY_REWRITE = (FieldRef("file name: <conversation id>.<signature>.jsonl", ROLE_KEY),)
_PIPE_REWRITE = (FieldRef("file name: tmux_<tmux name>.pipe", ROLE_KEY),)
_TASK_REWRITE = (FieldRef("folder name: <item id>", ROLE_KEY), FieldRef(f"{work_tables.MESSAGES}.parts#files[].path", ROLE_PATH))
_DESK_REWRITE = (FieldRef("folder name: <agent id>", ROLE_KEY),)
_SETTINGS_REWRITE = (FieldRef("file name: <agent id>.json", ROLE_KEY), FieldRef("env and hook paths inside", ROLE_PATH))
_THEME_REWRITE = (FieldRef("<folder>/.cc.theme", ROLE_PATH),)
_MEMORY_REWRITE = (FieldRef("projects/<ENC(cwd)>", ROLE_PATH),)
_FOLDER_REWRITE = (FieldRef("root", ROLE_PATH),)


def _children(folder: Path) -> List[Path]:
    try:
        return sorted(folder.iterdir())
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("inventory_folder_unreadable", path=str(folder), error=type(exc).__name__)
        return []


def _ids_where(conn: sqlite3.Connection, table: str, scope: Scope, store: str) -> List[int]:
    where = registry.book().where_of(scope, store, table)
    if where is None:
        return []
    try:
        return [int(r[0]) for r in conn.execute(f"SELECT id FROM {table} WHERE {where[0]}", where[1])]
    except sqlite3.Error as exc:
        logger.warning("inventory_ids_unreadable", store=store, table=table, error=str(exc))
        return []


def claimed_item_ids(conn: sqlite3.Connection, scope: Scope) -> List[int]:
    return _ids_where(conn, work_tables.ITEMS, scope, MAIN_STORE)


def _dirs_named(parent: Path, names: Iterable[str], store: str, reason: str, rewrite: Sequence[FieldRef],
                blockers: List[str], derived: bool = False) -> List[Artifact]:
    out: List[Artifact] = []
    for name in names:
        path = parent / name
        if os.path.lexists(path):
            art = measured_artifact(store, str(path), parent, REPORT, reason, blockers, rewrite, derived=derived)
            if art is not None:
                out.append(art)
    return out


def _restore_points(locations: Locations, conversations: Sequence[str], blockers: List[str]) -> List[Artifact]:
    tree = tree_root(locations.state_dir)
    out: List[Artifact] = []
    for slug in _children(tree):
        if slug.name.startswith(".") or not slug.is_dir():
            continue
        out += _dirs_named(slug, conversations, STORE_POINTS, "the conversation's restore points (the save plugin's backups)",
                           _POINT_REWRITE, blockers)
    return out


def _backup_copies(locations: Locations, conversations: Sequence[str], blockers: List[str]) -> List[Artifact]:
    folder = Path(locations.state_dir) / BACKUP_COPY_DIR
    names = [c.name for c in _children(folder)]
    out: List[Artifact] = []
    for conv in conversations:
        for name in (n for n in names if n.startswith(conv + ".") and n.endswith(".jsonl")):
            art = measured_artifact(STORE_BACKUP_COPIES, str(folder / name), folder, REPORT,
                                    "a plain copy the deep search index points at; derived, disposable", blockers,
                                    _COPY_REWRITE, derived=True)
            if art is not None:
                out.append(art)
    return out


def _pipe_log(locations: Locations, ident: SessionIdentity, blockers: List[str]) -> List[Artifact]:
    if not ident.tmux_name:
        return []
    from src.core.tmux_backend import PIPE_SUFFIX, _slugify

    path = Path(locations.state_dir) / f"tmux_{_slugify(ident.tmux_name)}{PIPE_SUFFIX}"
    if not path.is_file():
        return []
    art = measured_artifact(STORE_PIPE, str(path), Path(locations.state_dir), REPORT,
                            "keyed by tmux name, which a later session may reuse; the log is the pane's raw output",
                            blockers, _PIPE_REWRITE, derived=True)
    return [art] if art is not None else []


def _task_and_desk(locations: Locations, scope: Scope, main: sqlite3.Connection, blockers: List[str]) -> List[Artifact]:
    task_files = work_storage.folder(locations.state_dir) / TASK_FILES_DIR
    items = [str(i) for i in claimed_item_ids(main, scope)]
    out = _dirs_named(task_files, items, STORE_TASK_FILES,
                      f"files attached to the item (artifacts, pastes); the item rows name them in {work_tables.MESSAGES}.parts",
                      _TASK_REWRITE, blockers)
    desk = Path(locations.state_dir).joinpath(*SWARM_DESK_DIR)
    agents = [str(i) for i in _ids_where(main, "swarm_agents", scope, MAIN_STORE)]
    out += _dirs_named(desk, agents, STORE_DESK, "the Swarm agent's desk notes", _DESK_REWRITE, blockers)
    out += _dirs_named(Path(locations.state_dir).joinpath(*SWARM_SETTINGS_DIR), [f"{a}.json" for a in agents], STORE_SWARM_SETTINGS,
                       "the agent's claude --settings file, rewritten at each launch", _SETTINGS_REWRITE, blockers, derived=True)
    return out + _dirs_named(Path(locations.state_dir).joinpath(*SWARM_HOOKS_DIR), agents, STORE_SWARM_HOOKS,
                             "the agent's commit-guard hooks folder, rebuilt at each launch", _DESK_REWRITE, blockers, derived=True)


def _theme_dotfiles(folders: Iterable[Optional[str]], blockers: List[str]) -> List[Artifact]:
    out: List[Artifact] = []
    seen: Set[Path] = set()
    for folder in folders:
        path = theme_dotfile.project_theme_path(folder)
        if path is None or path in seen or not path.is_file():
            continue
        seen.add(path)
        art = measured_artifact(STORE_THEME_DOTFILE, str(path), path.parent, REPORT,
                                "the folder's project default theme, keyed on the directory", blockers, _THEME_REWRITE)
        if art is not None:
            out.append(art)
    return out


def session_files(main: sqlite3.Connection, scope: Scope, ident: SessionIdentity,
                  locations: Locations) -> Tuple[List[Artifact], List[str]]:
    blockers: List[str] = []
    safe = [c for c in scope.values(CONVERSATIONS) if SAFE_CONVERSATION.match(str(c))]
    arts = _restore_points(locations, safe, blockers) + _backup_copies(locations, safe, blockers)
    arts += vault_manifests(locations, safe, blockers)
    arts += _pipe_log(locations, ident, blockers)
    arts += _theme_dotfiles([ident.working_dir], blockers)
    return arts + _task_and_desk(locations, scope, main, blockers), blockers


def _project_dirs(locations: Locations, project: ProjectIdentity) -> List[Tuple[Path, Path]]:
    names = list(dict.fromkeys(slugify_project_dir(s) for s in (path_spellings(project.root) or [project.root])))
    out: List[Tuple[Path, Path]] = []
    seen: Set[str] = set()
    for home in locations.claude_homes():
        root = Path(home) / "projects"
        nested = [folder for rel, folder in project_folders(root) if "/" in rel and folder.name in names]
        for folder in [root / name for name in names] + nested:
            if folder.is_dir() and os.path.realpath(folder) not in seen:
                seen.add(os.path.realpath(folder))
                out.append((root, folder))
    return out


def _memory_and_orphans(locations: Locations, project: ProjectIdentity, claimed: Set[str],
                        blockers: List[str]) -> List[Artifact]:
    out: List[Artifact] = []
    for root, folder in _project_dirs(locations, project):
        notes = set(notes_entries(folder))
        for entry in _children(folder):
            if entry in notes:
                art = measured_artifact(STORE_MEMORY, str(entry), root, REPORT,
                                        "Claude's notes for the project, shared by every session in it", blockers, _MEMORY_REWRITE)
            else:
                found = conversation_form(entry.name, entry.is_dir() and not entry.is_symlink())
                if found is None or not _CONVERSATION_ENTRY.match(found[0]) or found[0] in claimed:
                    continue
                art = measured_artifact(STORE_ORPHANS, str(entry), root, REPORT,
                                        "a conversation file in the project's folder that no session row of the project names",
                                        blockers, _MEMORY_REWRITE)
            if art is not None:
                out.append(art)
    return out


def project_files(main: sqlite3.Connection, scope: Scope, project: ProjectIdentity, locations: Locations,
                  claimed_conversations: Iterable[str]) -> Tuple[List[Artifact], List[str]]:
    blockers: List[str] = []
    arts = _memory_and_orphans(locations, project, set(claimed_conversations), blockers)
    arts += _task_and_desk(locations, scope, main, blockers)
    arts += _theme_dotfiles([project.root], blockers)
    if os.path.isdir(project.root):
        arts.append(Artifact(store=STORE_FOLDER, kind=KIND_DIR, what=project.root, count=0, action=REPORT,
                             reason="the project's code folder: carried by project_pack, named here and never walked",
                             locator={"path": project.root}, rewrite=list(_FOLDER_REWRITE)))
    return arts, blockers

