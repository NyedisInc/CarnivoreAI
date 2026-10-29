"""Repository layer for the ``sessions`` table (design doc section 3.3).

Hand-rolled sqlite3, matching src/core/db.py and src/core/project_store.py
house style. No ORM.

IDENTITY, WHICH IS THE WHOLE POINT OF THIS MODULE.

A session has two identities and they answer different questions:

  ``session_uuid``  stable EXTERNAL identity, minted by the app, never
                    reused, never recomputed. What a URL or a foreign key
                    should carry.
  the INSTANCE      ``(tmux_socket, tmux_name, tmux_created_epoch)``. What
                    a live ``tmux list-sessions`` row can be matched
                    against. From schema v40 it is also keyed on the
                    machine, ``host_key``, and enforced by
                    ``ux_sessions_host_instance`` (src/core/hosts/ddl.py).

The name is also not TRUSTWORTHY input. tmux permits ``|`` inside a
session name, which is the delimiter of the listing format, so the whole
triple was once forgeable from a name a caller chose. That is fixed in
src/core/tmux_listing_parse.py, not here, but it is worth knowing that
the values arriving at these functions are only as good as that parser.

WHAT THAT BUYS. When a session dies and a new one takes its name, the new
instance's epoch differs, so it does not match the old row, so NO
statement in this module touches the old row. The new instance gets its
own row with ``origin='observed'`` and a fresh ``session_uuid``; the old
row keeps its origin and its ``adopted_at`` byte for byte and falls to
``stopped`` at the next successful probe. Without the epoch, name reuse
would silently transfer an adoption to a process the user never claimed
and badge it as his.

NOTHING EVER DELETES A SESSIONS ROW, AND THAT IS A KNOWN GAP.
Verified by walking the source rather than by grep: no statement
anywhere in ``src/`` issues ``DELETE FROM sessions``. There is no
reaper, no expiry, no repair path, and no UI affordance that removes
one. Combined with the ownership resolver's tier 2 - where ANY stored
instance for a name is a specific epoch-keyed opinion that returns
False for every other epoch - this makes a wrong ``owned`` row a
PERMANENT negative opinion about that name. A user who hits one has no
way back short of editing cloude.db by hand.

The mitigations that exist are all upstream, and they are why this is a
gap rather than an active defect: a NULL epoch is filtered out of
:func:`owned_instances` so it can never become such an opinion, and
:func:`src.core.session_import_mapping._stopped_epoch` no longer invents
a 0 that would have created one on every upgrade. So the known routes to
a wrong row are closed. What is missing is what happens if a new one
ever appears.

THE INTENDED REPAIR PATH, when it is built, is a REAPER keyed on the
instance triple: any row whose ``(socket, name, epoch)`` is absent from
a live listing, and whose ``lifecycle`` has been ``stopped`` for longer
than a retention window, may be deleted.

Its one non-negotiable precondition, stated here because it is the part
that is easy to leave out and catastrophic to miss: the reaper MUST run
only against a listing with ``ok=True``. An unavailable listing carries
no rows BY CONTRACT, not because there are none, so reaping against one
would delete the user's entire session history the first time tmux
failed to answer - turning a transient probe failure into permanent
data loss. Until that reaper exists, treat every row this module returns
as immortal.

WHERE THE WRITES LIVE. This module is the READ side. Everything that
can create, claim or refuse a row is in src/core/session_identity.py,
because those are the only operations that can get identity wrong.

THE ONE-SECOND COLLISION. ``#{session_created}`` has one-second
resolution, so a session killed and recreated with the same name inside
the same second produces a colliding triple. Two things resolve it, and
the second was added because the first covered only the rarer half:

  ``sessions.tmux_session_id`` (schema v3) stores tmux's
  ``#{session_id}``, which is unique per server lifetime. When the stored
  and incoming ids DISAGREE the rows are provably different sessions and
  the merge is refused whatever the stored lifecycle says. It is a
  DISCRIMINATOR and never a key: the id counter restarts at ``$0`` when
  the tmux server does, so it is worse than the epoch as a durable
  identity and better than it at separating two sessions alive right now.

  A stored row already marked ``stopped`` CANNOT be the live session we
  are looking at, so that merge is refused too.

In both cases the correct action is to REFUSE THE MERGE AND LOG - never
to overwrite. See :func:`record_instance` and design section 4.6.

THE LEGACY NAME SET IS A SEPARATE, LOWER TIER. It is NOT folded into
:func:`owned_instances`. It used to be, as ``(tmux_name, None)``, which
the listing backend read as a name-only WILDCARD - and that disabled the
epoch tier for every session the app had created since the last restart,
which is exactly the population the epoch protects. Legacy names now
travel as their own argument and are resolved after a stored epoch has
had its say. See :func:`src.core.tmux_listing_parse.resolve_ownership`.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core.companion_shell.rows import exclude_clause
from src.core.db import column_exists, table_exists
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.db_models import (
    DEFAULT_TMUX_SOCKET,
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_LIFECYCLE_UNKNOWN,
    SESSION_ORIGIN_OBSERVED,
    SESSION_OWNED_ORIGINS,
)
from src.core.session_kind import KIND_AUTOMATED as SESSION_KIND_AUTOMATED

logger = structlog.get_logger()

SESSIONS_TABLE = "sessions"
PROJECTS_TABLE = "projects"


class SessionInstanceMismatchError(LookupError):
    pass


class SessionNotFoundError(LookupError):
    pass

def sessions_table_ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, SESSIONS_TABLE)


def _project_join_ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, PROJECTS_TABLE) and column_exists(
        conn, SESSIONS_TABLE, "project_id"
    )


def get_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return None
    if epoch is None:
        return None
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        "SELECT * FROM sessions WHERE tmux_socket = ? AND tmux_name = ? "
        f"AND tmux_created_epoch = ?{scope_sql}",
        (socket, name, int(epoch), *scope_params),
    ).fetchone()
    return dict(row) if row is not None else None


def owned_instances(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET,
    host_key: str = LOCAL_HOST_KEY,
) -> Set[Tuple[str, int]]:
    if not sessions_table_ready(conn):
        return set()
    placeholders = ", ".join("?" for _ in SESSION_OWNED_ORIGINS)
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT tmux_name, tmux_created_epoch FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND origin IN ({placeholders}) "
        "AND tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL",
        (socket, *scope_params, *SESSION_OWNED_ORIGINS),
    ).fetchall()
    return {(str(row[0]), int(row[1])) for row in rows}


def owned_names(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET
) -> Set[str]:
    return {name for name, _epoch in owned_instances(conn, socket=socket)}


def list_sessions(
    conn: sqlite3.Connection,
    *,
    lifecycle: Optional[str] = None,
    include_archived: bool = True,
    include_lineage: bool = False,
    include_automated: bool = True,
    include_companions: bool = False,
) -> List[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return []
    clauses: List[str] = []
    values: List[Any] = []
    if lifecycle is not None:
        clauses.append("s.lifecycle = ?")
        values.append(lifecycle)
    if not include_archived:
        clauses.append("s.archived_at IS NULL")
    if not include_lineage:
        clauses.append(
            "(s.parent_session_id IS NULL OR s.tmux_created_epoch IS NOT NULL)"
        )
    if not include_automated and column_exists(conn, "sessions", "kind"):
        clauses.append("COALESCE(s.kind, '') <> ?")
        values.append(SESSION_KIND_AUTOMATED)
    if not include_companions:
        companion = exclude_clause(conn, "s")
        if companion:
            clauses.append(companion[len(" AND "):])
    project_ready = _project_join_ready(conn)
    if project_ready:
        query = (
            "SELECT s.*, p.display_name AS project_name FROM sessions s "
            "LEFT JOIN projects p ON p.id = s.project_id"
        )
    else:
        query = "SELECT s.*, NULL AS project_name FROM sessions s"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY s.id DESC"
    return [dict(row) for row in conn.execute(query, values).fetchall()]


def listable_sessions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Every stored session a USER-FACING LISTING may show, newest first.

      The rule has two halves and they are NOT the same idea:

        ENDED (``lifecycle='stopped'``) IS INCLUDED. A session whose
        tmux instance is gone still has a name, a project, a working
        directory and a history the user put there. Hiding it is how he
        loses track of work he did.

      ``lifecycle='unknown'`` is deliberately still returned. It is a
      CANNOT DETERMINE, not an absence, and the caller routes it into
      NEEDS ATTENTION rather than dropping it - suppressing it here
      would turn "we could not evaluate this" into "there is nothing
      here", which is the collapse this project keeps removing.

      Lineage rows stay out, inherited from :func:`list_sessions`'s
      default: a lineage row describes a past CONVERSATION inside a tmux
      session, not a session of its own.
    Inputs: conn (sqlite3.Connection).
    Output: list[dict] - empty on a pre-v2 database. That emptiness is an
      absence of a TABLE, not an answer about sessions; callers that need
      to tell those apart ask GET /sessions/import-status.
    Example: listable_sessions(conn)  # [{'session_uuid': 'u1', ...}]
    """
    return list_sessions(
        conn, include_archived=False, include_automated=False
    )


def archive_session(
    conn: sqlite3.Connection,
    session_uuid: str,
    *,
    now: Optional[str] = None,
) -> bool:
    from src.core.trail_entry import utc_now

    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT archived_at FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)
    if row["archived_at"] is not None:
        return False

    stamp = now or utc_now()
    conn.execute(
        "UPDATE sessions SET archived_at = ?, updated_at = ? "
        "WHERE session_uuid = ? AND archived_at IS NULL",
        (stamp, stamp, session_uuid),
    )
    conn.commit()
    logger.info(
        "session_archived", session_uuid=session_uuid, archived_at=stamp
    )
    return True


def unarchive_session(
    conn: sqlite3.Connection,
    session_uuid: str,
    *,
    now: Optional[str] = None,
) -> bool:
    from src.core.trail_entry import utc_now

    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT archived_at FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)
    if row["archived_at"] is None:
        return False

    stamp = now or utc_now()
    conn.execute(
        "UPDATE sessions SET archived_at = NULL, updated_at = ? "
        "WHERE session_uuid = ? AND archived_at IS NOT NULL",
        (stamp, session_uuid),
    )
    conn.commit()
    logger.info("session_unarchived", session_uuid=session_uuid)
    return True


def notification_policy_rows(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET
) -> List[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return []
    if not column_exists(conn, SESSIONS_TABLE, "notifications_muted"):
        return []
    if not column_exists(
        conn, SESSIONS_TABLE, "notification_policy_generation"
    ):
        return []
    rows = conn.execute(
        "SELECT session_uuid, tmux_socket, tmux_name, tmux_created_epoch, "
        "notifications_muted, notification_policy_generation "
        "FROM sessions "
        "ORDER BY tmux_created_epoch ASC, id ASC"
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        epoch = row.get("tmux_created_epoch")
        try:
            epoch_value = int(epoch) if epoch is not None else None
        except (TypeError, ValueError):
            epoch_value = None
        out.append(
            {
                "session_uuid": row.get("session_uuid"),
                "tmux_socket": row.get("tmux_socket") or socket,
                "tmux_name": row.get("tmux_name"),
                "tmux_created_epoch": epoch_value,
                "muted": bool(row.get("notifications_muted")),
                "generation": int(
                    row.get("notification_policy_generation") or 0
                ),
            }
        )
    return out


def get_notification_policy(
    conn: sqlite3.Connection, session_uuid: str
) -> Dict[str, Any]:
    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    if not column_exists(conn, SESSIONS_TABLE, "notifications_muted"):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT notifications_muted, notification_policy_generation "
        "FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)
    return {
        "muted": bool(row["notifications_muted"]),
        "generation": int(row["notification_policy_generation"] or 0),
    }


def set_notification_mute(
    conn: sqlite3.Connection,
    session_uuid: str,
    *,
    muted: bool,
    expected_tmux_name: Optional[str] = None,
    expected_tmux_created_epoch: Optional[int] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Record whether this session's notifications are muted. Durably.

    Description: THE ONLY WRITER of ``sessions.notifications_muted`` and
      of ``sessions.notification_policy_generation``, so the ordering of
      policy changes has exactly one author.

      A NO-OP DOES NOT STEP IT. Muting an already-muted session returns
      the current generation unchanged and writes nothing. Stepping there
      would invalidate every queued notification each time a client
      re-sent the state it already had, which is a way to lose alerts
      nobody asked to lose.
    """
    from src.core.trail_entry import utc_now

    if not sessions_table_ready(conn):
        raise SessionNotFoundError(session_uuid)
    if not column_exists(conn, SESSIONS_TABLE, "notifications_muted"):
        raise SessionNotFoundError(session_uuid)
    row = conn.execute(
        "SELECT tmux_name, tmux_created_epoch, notifications_muted, "
        "notification_policy_generation FROM sessions WHERE session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_uuid)

    if expected_tmux_name is not None and expected_tmux_created_epoch is not None:
        stored_epoch = row["tmux_created_epoch"]
        try:
            stored_epoch = (
                int(stored_epoch) if stored_epoch is not None else None
            )
        except (TypeError, ValueError):
            stored_epoch = None
        if (
            row["tmux_name"] != expected_tmux_name
            or stored_epoch != int(expected_tmux_created_epoch)
        ):
            logger.warning(
                "session_notification_mute_instance_mismatch",
                session_uuid=session_uuid,
                expected_tmux_name=expected_tmux_name,
                expected_epoch=int(expected_tmux_created_epoch),
                stored_tmux_name=row["tmux_name"],
                stored_epoch=stored_epoch,
            )
            raise SessionInstanceMismatchError(session_uuid)

    current_muted = bool(row["notifications_muted"])
    current_generation = int(row["notification_policy_generation"] or 0)
    wanted = bool(muted)
    stored_name = row["tmux_name"]
    try:
        stored_epoch_out = (
            int(row["tmux_created_epoch"])
            if row["tmux_created_epoch"] is not None
            else None
        )
    except (TypeError, ValueError):
        stored_epoch_out = None

    if current_muted == wanted:
        return {
            "muted": current_muted,
            "generation": current_generation,
            "changed": False,
            "tmux_name": stored_name,
            "tmux_created_epoch": stored_epoch_out,
        }

    next_generation = current_generation + 1
    stamp = now or utc_now()
    conn.execute(
        "UPDATE sessions SET notifications_muted = ?, "
        "notification_policy_generation = ?, updated_at = ? "
        "WHERE session_uuid = ?",
        (1 if wanted else 0, next_generation, stamp, session_uuid),
    )
    conn.commit()
    logger.info(
        "session_notification_mute_set",
        session_uuid=session_uuid,
        muted=wanted,
        policy_generation=next_generation,
    )
    return {
        "muted": wanted,
        "generation": next_generation,
        "changed": True,
        "tmux_name": stored_name,
        "tmux_created_epoch": stored_epoch_out,
    }


def needs_attention(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Return the rows the home screen must surface as CANNOT DETERMINE.

    Description: design section 4.3's NEEDS ATTENTION group, restricted
      to what the sessions table itself can answer: a row whose lifecycle
      could not be evaluated, or whose project attribution could not be
      evaluated. This group exists so the third outcome reaches the
      roll-up instead of being folded into RUNNING or RECENT. Empty on a
      healthy machine, which is the point.
    """
    if not sessions_table_ready(conn):
        return []
    # could not
    rows = conn.execute(
        "SELECT * FROM sessions "
        "WHERE (lifecycle = ? OR project_attribution = ?) "
        "AND parent_session_id IS NULL "
        "AND archived_at IS NULL"
        + exclude_clause(conn)
        + " ORDER BY id DESC",
        (SESSION_LIFECYCLE_UNKNOWN, SESSION_ATTRIBUTION_UNKNOWN),
    ).fetchall()
    return [dict(row) for row in rows]


def count_sessions(conn: sqlite3.Connection) -> int:
    if not sessions_table_ready(conn):
        return 0
    row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
    return int(row[0]) if row else 0


def is_owned_origin(origin: Optional[str]) -> bool:
    return origin in SESSION_OWNED_ORIGINS


def observed_origin_for(name: str, owned_tmux_names: Set[str]) -> str:
    from src.core.db_models import SESSION_ORIGIN_CREATED

    return (
        SESSION_ORIGIN_CREATED
        if name in owned_tmux_names
        else SESSION_ORIGIN_OBSERVED
    )


def identity_for_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[Dict[str, Any]]:
    if not sessions_table_ready(conn) or not name or epoch is None:
        return None
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        "SELECT id, parent_session_id, agent_type, agent_family, "
        "agent_family_source FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ?",
        (socket, *scope_params, name, epoch),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "parent_session_id": row["parent_session_id"],
        "agent_type": row["agent_type"],
        "agent_family": row["agent_family"],
        "agent_family_source": row["agent_family_source"],
    }


def identity_for_live_name(
    conn: sqlite3.Connection, *, socket: str, name: str, host_key: str = LOCAL_HOST_KEY
) -> Optional[Dict[str, Any]]:
    """Row identity for a LIVE tmux session, keyed on name alone.

    Description: the exact-key :func:`identity_for_instance` needs an
      epoch, and a live SessionInfo does not carry one - it knows the tmux
      NAME it is attached to and nothing more. So this takes the NEWEST
      instance for that name, which for a live session is the right row by
      construction: the pane you are attached to is the most recent
      instance of that name, and any older row with the same name is a
      dead session whose name was reused.

      That is a weaker guarantee than the exact key, and it is stated
      rather than hidden. Use :func:`identity_for_instance` wherever an
      epoch is available.
    Inputs: conn (sqlite3.Connection). socket (str). name (str).
      host_key (str) - the machine the socket is on (issue #162).
    Output: dict with ``id``, ``parent_session_id``, ``agent_type``,
      ``agent_family`` and ``agent_family_source``, or None when no row
      carries that name. THE LAST THREE TRAVEL TOGETHER: ``agent_type``
      alone cannot say whether it was launched or inferred from the
      pane's process tree, and a caller that reads one without the other
      renders a guess as a fact (see
      src/core/session_agent_evidence.py). ``agent_family`` is the
      family the LAUNCHER resolved and stored; without it a caller can
      only re-derive one from ``agent_type`` against the config as it
      stands now, which answers nothing for a wrapper that has since
      been deleted.

      ALSO ``project_id`` AND ``project_name``, which the conversations
      drawer groups on. Both are always present and both are None when
      the binding could not be read - an unmigrated database, a deleted
      project row, or a session that genuinely has none. None means
      "could not be determined" and is never a guess; the client files
      such a session under its own node rather than inventing a project
      from the working directory, because a symlinked path spells one
      folder two ways and would split a project in two.
    Example: identity_for_live_name(conn, socket='cloude', name='a')
    """
    if not sessions_table_ready(conn) or not name:
        return None
    project_ready = _project_join_ready(conn)
    if project_ready:
        scope_sql, scope_params = host_scope(conn, host_key, column="s.host_key")
        row = conn.execute(
            "SELECT s.id, s.parent_session_id, s.agent_type, s.agent_family, "
            "s.agent_family_source, s.claude_session_uuid, s.launch_record, s.project_id, "
            "p.display_name AS project_name "
            "FROM sessions s "
            "LEFT JOIN projects p ON p.id = s.project_id "
            f"WHERE s.tmux_socket = ?{scope_sql} AND s.tmux_name = ? "
            "AND s.tmux_created_epoch IS NOT NULL "
            "ORDER BY s.tmux_created_epoch DESC, s.id DESC LIMIT 1",
            (socket, *scope_params, name),
        ).fetchone()
    else:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT id, parent_session_id, agent_type, agent_family, "
            "agent_family_source, claude_session_uuid, launch_record "
            "FROM sessions "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? "
            "AND tmux_created_epoch IS NOT NULL "
            "ORDER BY tmux_created_epoch DESC, id DESC LIMIT 1",
            (socket, *scope_params, name),
        ).fetchone()
    if row is None:
        return None
    # could not be read
    project_id = row["project_id"] if project_ready else None
    project_name = row["project_name"] if project_ready else None
    return {
        "id": int(row["id"]),
        "parent_session_id": row["parent_session_id"],
        "agent_type": row["agent_type"],
        "agent_family": row["agent_family"],
        "agent_family_source": row["agent_family_source"],
        # conversation id
        "claude_session_uuid": row["claude_session_uuid"] or None,
        "launch_record": row["launch_record"],
        "project_id": int(project_id) if project_id is not None else None,
        "project_name": project_name,
    }
