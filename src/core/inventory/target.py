"""Resolve a ``target`` to one ``sessions`` row or one ``projects`` row, archived and shadowed rows included. Reads only.

The inventory (and a purge before it) exists to account for rows the listings no longer show, so it resolves against
the tables themselves, never the live or asleep listing.

A SESSION target is accepted in this order (the first form that matches wins):

1. ``session_uuid`` (the durable id);
2. a ``ses_`` app id, matched to ``sessions.legacy_session_id`` (the id the app minted for the row);
3. a DB row id, ``row:<id>`` (the form the unread store and terminal slots use) or a bare integer;
4. a conversation id: the row's current ``claude_session_uuid``, else the one session the conversation index says
   ran it (a conversation two sessions ran is refused with their ``session_uuid`` values);
5. a tmux name, ONLY when exactly one row carries it. A name two rows share (a recreate keeps the old row)
   is refused with the candidate ``session_uuid`` values, because a tmux name is not a session's identity.

A PROJECT target is a ``projects.id`` (``project:<id>`` or a bare integer), a ``projects.uid``, the project's folder
(an absolute path, compared by real path) or its display name when exactly one project carries it.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import List

from src.core.db import table_exists
from src.core.inventory.model import ProjectNotFound

_ROW_FORM = re.compile(r"^(?:row:)?(\d{1,12})$")
_PROJECT_FORM = re.compile(r"^(?:project:)?(\d{1,12})$")
_APP_ID_PREFIX = "ses_"
_MAX_CANDIDATES = 8


class TargetNotFound(LookupError):
    pass


class TargetAmbiguous(LookupError):

    def __init__(self, message: str, candidates: List[str]) -> None:
        super().__init__(message)
        self.candidates = candidates


def _uuids(conn: sqlite3.Connection, where: str, param: object) -> List[str]:
    return [str(r[0]) for r in conn.execute(f"SELECT session_uuid FROM sessions WHERE {where} ORDER BY id", (param,))]


def _indexed_runners(conn: sqlite3.Connection, conversation: str) -> List[str]:
    if not table_exists(conn, "conversation_index"):
        return []
    sql = ("SELECT s.session_uuid FROM sessions s WHERE s.session_uuid IN "
           "(SELECT session_uuid FROM conversation_index WHERE conversation_id = ?) ORDER BY s.id")
    return [str(r[0]) for r in conn.execute(sql, (conversation,))]


def _ambiguous(kind: str, text: str, hits: List[str]) -> TargetAmbiguous:
    shown = ", ".join(hits[:_MAX_CANDIDATES])
    return TargetAmbiguous(f"{len(hits)} session rows carry the {kind} {text!r}: use one of their "
                           f"session_uuid values ({shown})", hits)


def resolve_session_uuid(conn: sqlite3.Connection, target: str) -> str:
    text = target.strip()
    hits = _uuids(conn, "session_uuid = ?", text)
    if not hits and text.startswith(_APP_ID_PREFIX):
        hits = _uuids(conn, "legacy_session_id = ?", text)
    if not hits:
        match = _ROW_FORM.match(text)
        if match:
            hits = _uuids(conn, "id = ?", int(match.group(1)))
    if not hits:
        hits = _uuids(conn, "claude_session_uuid = ?", text) or _indexed_runners(conn, text)
        if len(hits) > 1:
            raise _ambiguous("conversation", text, hits)
    if not hits:
        hits = _uuids(conn, "tmux_name = ?", text)
        if len(hits) > 1:
            raise _ambiguous("name", text, hits)
    if not hits:
        raise TargetNotFound(f"no stored session matches target {text!r}")
    return hits[0]


def _project_ids(conn: sqlite3.Connection, where: str, param: object) -> List[int]:
    return [int(r[0]) for r in conn.execute(f"SELECT id FROM projects WHERE {where} ORDER BY id", (param,))]


def resolve_project_id(conn: sqlite3.Connection, target: str) -> int:
    text = target.strip()
    match = _PROJECT_FORM.match(text)
    hits = _project_ids(conn, "id = ?", int(match.group(1))) if match else []
    if not hits:
        hits = _project_ids(conn, "uid = ?", text)
    if not hits and os.path.isabs(text):
        hits = _project_ids(conn, "root = ?", text) or _project_ids(conn, "root = ?", os.path.realpath(text))
    if not hits:
        hits = _project_ids(conn, "display_name = ?", text)
        if len(hits) > 1:
            raise ProjectNotFound(f"{len(hits)} projects are named {text!r}: use a project id or its folder")
    if not hits:
        raise ProjectNotFound(f"no stored project matches target {text!r}")
    return hits[0]
