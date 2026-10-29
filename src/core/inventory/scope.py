
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from src.core.inventory import identity
from src.core.inventory.model import SCOPE_PROJECT, SCOPE_SESSION, ProjectIdentity, SessionIdentity
from src.core.stats.plugin.extract import project_key

SESSION_ROW_IDS = "session_row_ids"
SESSION_UUIDS = "session_uuids"
APP_IDS = "app_ids"
TMUX_NAMES = "tmux_names"
TMUX_KEYS = "tmux_keys"
CONVERSATIONS = "conversations"
PRIMARY_CONVERSATIONS = "primary_conversations"
EARLIER_CONVERSATIONS = "earlier_conversations"
PROJECT_IDS = "project_ids"
PROJECT_UIDS = "project_uids"
PROJECT_NAMES = "project_names"
PROJECT_ROOTS = "project_roots"
LIST_KEYS = "list_keys"
COMPANY_IDS = "company_ids"
GRANT_SCOPES = "grant_scopes"
STATS_PROJECTS = "stats_project_keys"


@dataclass(frozen=True)
class Scope:

    kind: str
    keys: Dict[str, Tuple[Any, ...]] = field(default_factory=dict)

    def values(self, key: str) -> List[Any]:
        return list(self.keys.get(key, ()))


def _add(keys: Dict[str, List[Any]], name: str, values: Iterable[Any]) -> None:
    bucket = keys.setdefault(name, [])
    for value in values:
        if value not in (None, "") and value not in bucket:
            bucket.append(value)


def _add_session(keys: Dict[str, List[Any]], conn: sqlite3.Connection, ident: SessionIdentity) -> None:
    _add(keys, SESSION_ROW_IDS, [ident.row_id])
    _add(keys, SESSION_UUIDS, [ident.session_uuid])
    _add(keys, APP_IDS, [ident.app_id])
    _add(keys, TMUX_NAMES, [ident.tmux_name])
    if ident.tmux_name:
        _add(keys, TMUX_KEYS, [ident.layout_key] + ([] if ident.tmux_epoch is None else [f"{ident.tmux_name}@{ident.tmux_epoch}"]))
    _add(keys, PRIMARY_CONVERSATIONS, [ident.conversation])
    earlier = identity.related_conversations(conn, ident)
    _add(keys, CONVERSATIONS, [ident.conversation, *earlier])
    _add(keys, EARLIER_CONVERSATIONS, earlier)


def session_scope(conn: sqlite3.Connection, ident: SessionIdentity) -> Scope:
    keys: Dict[str, List[Any]] = {}
    _add_session(keys, conn, ident)
    return Scope(SCOPE_SESSION, {k: tuple(v) for k, v in keys.items()})


def project_scope(project: ProjectIdentity) -> Scope:
    keys: Dict[str, List[Any]] = {}
    _add(keys, PROJECT_IDS, [project.project_id])
    _add(keys, PROJECT_UIDS, [project.uid])
    _add(keys, PROJECT_NAMES, [project.name])
    _add(keys, PROJECT_ROOTS, [project.root, project.raw_path])
    _add(keys, LIST_KEYS, [project.list_key])
    _add(keys, COMPANY_IDS, [project.company_id])
    _add(keys, GRANT_SCOPES, [f"project:{project.project_id}"])
    _add(keys, STATS_PROJECTS, [project_key(folder) for folder in (project.root, project.raw_path) if folder])
    return Scope(SCOPE_PROJECT, {k: tuple(v) for k, v in keys.items()})
