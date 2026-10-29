"""The user-facing LABEL, and the lossy filter that derives a tmux name.

TWO THINGS THAT WERE ONE THING. A session's displayed name and its tmux
session name were the same string, so renaming a session meant
``tmux rename-session``, which moves the one field the identity key
``(socket, name, epoch)`` was built on. The stored row stopped matching
the live listing, the reaper called it dead, and the same live session
came back through the adopt path as a stranger and got a second row. One
session, two rows, one of them a corpse.

Separating them does not patch that path - it makes it UNREACHABLE from
the rename surface. A label lives in ``sessions.title``. Changing it
writes one column. The tmux name and the creation epoch never move, so
the identity triple is never touched by a rename at all.

It also removes a restriction the user asked to have removed: the old
rename endpoint enforced ``^[A-Za-z0-9_-]{1,64}$``, so "Media
Compression" was not a legal session name. A label is a label; it takes
what a human types.

WHAT WAS MEASURED ABOUT TMUX, RATHER THAN ASSUMED. On a throwaway socket,
``new-session -s`` ACCEPTED every one of: a space, ``:``, ``.``, ``/``,
``"``, ``$``. So tmux is far more permissive than the old validator
implied. Two real constraints remain:

  NON-ASCII IS NOT PRESERVED. A session created as ``emoji 🚀 ok`` reads
  back from ``list-sessions`` as ``emoji __ ok``. tmux mangles it, so a
  derived name containing one would not round-trip and every lookup by
  name would miss.

  ``:`` AND ``.`` ARE TARGET SYNTAX. tmux's ``-t`` grammar splits on
  them, so a name carrying either is legal to CREATE and awkward to
  ADDRESS - which is what every other call site in this codebase does.

Neither constrains the LABEL, because the label is never handed to tmux.

THE FILTER IS LOSSY AND THEREFORE NOT AN IDENTITY. ``client: acme`` and
``client. acme`` both sanitise to ``client_acme``. That is deliberate and
safe here precisely because the tmux name no longer identifies anything
on its own - the row is identified by ``(socket, name, epoch)`` and, for
a rename, by ``(epoch, #{session_id})``. The collision is resolved by
appending a suffix, never by rejecting the user's label, and never by
letting two live sessions share a tmux name.

WHY THIS DOES NOT DISTURB SIDEBAR GROUPS. Group membership is keyed on
``tmux_name`` on purpose: an unadopted tmux session has no ``sessions``
row to key on, so a row-keyed membership could not represent it at all.
That reasoning is untouched here. The tmux name is now MORE stable than
before, not less - nothing renames it after creation - so the group key
is strictly safer than it was.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from typing import Iterable, Optional, Set

import structlog

from src.core.product_identity import strip_session_prefix
from src.core.trail_entry import utc_now
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()

LABEL_MAX_CHARS: int = 200

TMUX_NAME_MAX_CHARS: int = 64

APP_TMUX_PREFIX = "cloude_"

# nothing at all
FALLBACK_TMUX_NAME = "session"

_UNSAFE_FOR_TMUX = re.compile(r"[\s:./\\'\"`$;|&<>(){}\[\]*?!#%^~,=+@]+")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class InvalidLabel(ValueError):
    pass


def validate_label(label: Optional[str]) -> str:
    if label is None:
        raise InvalidLabel("a session label cannot be empty")
    cleaned = label.strip()
    if not cleaned:
        raise InvalidLabel("a session label cannot be empty")
    if len(cleaned) > LABEL_MAX_CHARS:
        raise InvalidLabel(
            f"a session label may be at most {LABEL_MAX_CHARS} characters"
        )
    if _CONTROL_CHARS.search(cleaned):
        raise InvalidLabel(
            "a session label cannot contain control characters such as a "
            "newline or a tab"
        )
    return cleaned


def sanitize_tmux_name(label: str) -> str:
    folded = unicodedata.normalize("NFKD", label or "")
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    replaced = _UNSAFE_FOR_TMUX.sub("_", ascii_only)
    replaced = re.sub(r"_+", "_", replaced).strip("_")
    trimmed = replaced[:TMUX_NAME_MAX_CHARS].strip("_")
    return trimmed or FALLBACK_TMUX_NAME


def unique_tmux_name(label: str, *, taken: Iterable[str]) -> str:
    """Derive a tmux name that no live session already holds.

    Description: the collision half of a lossy filter. Two labels CAN
      sanitise to one name, and the answer is a suffix rather than a
      rejection: the user's label is theirs and is stored intact, while
      the tmux name is an internal handle that nobody reads and nothing
      identifies a session by on its own.

      The walk is BOUNDED. ``_2`` through ``_49``, and if every one of
      those is taken it falls back to an 8-hex-character digest of the
      label plus the taken-set size, which cannot loop. An unbounded
      "keep incrementing" would be a hang under a pathological set, and
      a hang in the create path is worse than an ugly name.
    Inputs: label (str) - the user's label. taken (Iterable[str]) - the
      names already in use on this socket.
    Output: str - a name not present in ``taken``.
    Example: unique_tmux_name('acme', taken={'acme'})  # 'acme_2'
    """
    used: Set[str] = set(taken)
    base = sanitize_tmux_name(label)
    if base not in used:
        return base
    room = max(1, TMUX_NAME_MAX_CHARS - 4)
    stem = base[:room].strip("_") or FALLBACK_TMUX_NAME
    for suffix in range(2, 50):
        candidate = f"{stem}_{suffix}"
        if candidate not in used:
            return candidate
    digest = hashlib.sha256(
        f"{label}|{len(used)}".encode("utf-8")
    ).hexdigest()[:8]
    return f"{stem[: TMUX_NAME_MAX_CHARS - 9]}_{digest}"


def label_from_tmux_name(tmux_name: Optional[str]) -> Optional[str]:
    if not tmux_name:
        return None
    stem = tmux_name
    remainder = strip_session_prefix(stem)
    if remainder:
        stem = remainder
    return stem.replace("_", " ").strip() or tmux_name


def set_label(
    conn: sqlite3.Connection,
    *,
    session_uuid: str,
    label: str,
    now: Optional[str] = None,
) -> bool:
    cleaned = validate_label(label)
    stamp = now or utc_now()
    cursor = conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE session_uuid = ?",
        (cleaned, stamp, session_uuid),
    )
    if cursor.rowcount > 0:
        logger.info(
            "session_label_set",
            session_uuid=session_uuid,
            note="title only; no identity column is in this statement",
        )
        return True
    logger.warning(
        "session_label_no_such_row",
        session_uuid=session_uuid,
        note="no row carries that session_uuid, so nothing was labelled",
    )
    return False


def set_label_for_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    label: str,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> bool:
    cleaned = validate_label(label)
    if epoch is None:
        logger.warning(
            "session_label_no_epoch",
            tmux_socket=socket,
            tmux_name=name,
            note=(
                "no creation epoch, so there is no instance to key on; "
                "nothing written rather than relabelling by name"
            ),
        )
        return False
    stamp = now or utc_now()
    scope_sql, scope_params = host_scope(conn, host_key)
    cursor = conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ?",
        (cleaned, stamp, socket, *scope_params, name, int(epoch)),
    )
    if cursor.rowcount > 0:
        logger.info(
            "session_label_set_for_instance",
            tmux_socket=socket,
            tmux_name=name,
            tmux_created_epoch=int(epoch),
            note="title only; no identity column is in the SET clause",
        )
        return True
    logger.warning(
        "session_label_no_such_instance",
        tmux_socket=socket,
        tmux_name=name,
        tmux_created_epoch=int(epoch),
        note="no row carries that instance triple, so nothing was labelled",
    )
    return False


def _clean_title(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def label_for_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[str]:
    if not name or epoch is None:
        return None
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT title FROM sessions "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ? "
            "ORDER BY id DESC LIMIT 1",
            (socket, *scope_params, name, int(epoch)),
        ).fetchone()
    except (sqlite3.Error, TypeError, ValueError) as exc:
        logger.debug("session_label_instance_read_threw", error=str(exc))
        return None
    if row is None:
        return None
    return _clean_title(dict(row).get("title"))


def label_for_name(
    conn: sqlite3.Connection, *, socket: str, name: str, host_key: str = LOCAL_HOST_KEY
) -> Optional[str]:
    if not name:
        return None
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT title FROM sessions "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? "
            "AND tmux_created_epoch IS NOT NULL "
            "ORDER BY tmux_created_epoch DESC, id DESC LIMIT 1",
            (socket, *scope_params, name),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("session_label_name_read_threw", error=str(exc))
        return None
    if row is None:
        return None
    return _clean_title(dict(row).get("title"))
