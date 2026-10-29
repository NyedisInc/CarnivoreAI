"""Every stored fact a listing needs about a tmux instance, read ONCE.

WHY THIS FILE EXISTS. ``SessionManager.list_attachable_sessions`` decorates
each row it is about to return with three things that all live on the SAME
``sessions`` row, found by the SAME key - the instance triple
``(tmux_socket, tmux_name, tmux_created_epoch)``:

  * the user-facing title            (``session_label.label_for_instance``)
  * the durable row id and its parent (``session_store.identity_for_instance``)
  * what the app recorded launching   (``session_agent_provenance.stored_launch_for``)

THE SHAPE IS THE SAME ONE ``session_status_map`` APPLIES TO TMUX: one bulk
read up front, then answer every row from it, instead of asking again per
row for something already fetched. Here it is one ``SELECT`` for all the
names in the listing rather than one bulk ``list-panes -a``.

THE TWO SELECTION RULES ARE NOT THE SAME AND BOTH ARE PRESERVED. Should a
triple ever carry more than one row, ``label_for_instance`` takes the
HIGHEST id (it asks for ``ORDER BY id DESC LIMIT 1``) while the other two
take whatever an unordered ``fetchone()`` hands back, which in practice is
the first row in table order. So this index keeps the FIRST row it sees
for identity and launch and the LAST for the title, having read them in
ascending id order. In the ordinary single-row case every rule agrees;
collapsing them to one would be a silent behaviour change in the case
nobody looks at, which is exactly where such changes hide.

THE PURE RULES ARE IMPORTED, NEVER RE-STATED. ``_clean_title`` and
``DEFINITE_LAUNCH_SOURCES`` decide what a title and a definite launch
ARE, and those decisions stay in the modules that own them - this file
only changes HOW MANY TIMES the row is fetched, never what the row means.
A second copy of either rule here would drift.

AND THE LISTING PATH USES IT TOO, WHICH IS WHY THE INDEX CARRIES FOUR
COLUMNS THE ATTACHABLE PATH NEVER READS. ``GET /sessions/list`` has the
same shape one layer down: ``session_status_seed_read.read_instance_row``
opens ITS OWN connection, per session, to read ``activity_state``,
``activity_state_at``, ``claude_session_uuid`` and ``working_dir`` off the
row found by the SAME instance triple. Those four therefore live on
:class:`InstanceFacts` beside the other five, and one query serves both
callers. The alternative - a second index for the second path - would be
two things keyed on one triple, which is how two readings of one row
become two answers the moment they disagree.

A READING THAT DID NOT RUN IS NOT A READING OF NOTHING, so the index
carries ``complete``, the same discipline ``session_status_map.StatusMap``
applies to the tmux listing. For a DECORATION an empty index is harmless:
a missing title renders as nothing, which is what the per-row read already
produced when the datastore would not open. For the SEED it is not: an
index that could not be built would answer "no row" for every session and
silently blank the status ladder for the whole pass. So ``complete`` is
True only when a query actually RAN - including a real answer of zero rows
- and the seed seam reads the index only then, falling back to its own
per-row read otherwise. That makes the change strictly non-regressive: the
worst case is the cost that was already being paid.

FAILURE DEGRADES EXACTLY AS THE PER-ROW READS DID. A datastore that
cannot be opened or queried yields an EMPTY index, and an empty index
answers ``None`` / ``NOT_KNOWN`` for every row - which is what each of the
three functions already returned in that case. The one behavioural
difference worth naming: a transient error now costs the decorations for
the whole pass rather than for one row. These are decorations on a list
that repolls every five seconds, and the alternative is paying 33
connections forever to make a rare transient failure slightly narrower.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.session_agent_provenance import (
    DEFINITE_LAUNCH_SOURCES,
    NOT_KNOWN,
    StoredLaunch,
)
from src.core.session_label import _clean_title

logger = logging.getLogger(__name__)

InstanceKey = Tuple[str, int]


@dataclass(frozen=True)
class InstanceFacts:

    title: Optional[str] = None
    row_id: Optional[int] = None
    parent_session_id: Optional[Any] = None
    agent_type: Optional[str] = None
    agent_family_source: Optional[str] = None
    agent_family: Optional[str] = None
    activity_state: Optional[str] = None
    activity_state_at: Optional[Any] = None
    claude_session_uuid: Optional[str] = None
    working_dir: Optional[str] = None


class InstanceIndex:

    def __init__(
        self,
        facts: Optional[Dict[InstanceKey, InstanceFacts]] = None,
        *,
        complete: bool = False,
    ):
        self._facts: Dict[InstanceKey, InstanceFacts] = dict(facts or {})
        self.complete: bool = bool(complete)

    def _get(self, name: Optional[str], epoch: Optional[int]) -> Optional[InstanceFacts]:
        if not name or epoch is None:
            return None
        try:
            return self._facts.get((name, int(epoch)))
        except (TypeError, ValueError):
            return None

    def label(self, name: Optional[str], epoch: Optional[int]) -> Optional[str]:
        facts = self._get(name, epoch)
        return facts.title if facts else None

    def identity(
        self, name: Optional[str], epoch: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        facts = self._get(name, epoch)
        if facts is None:
            return None
        return {
            "id": facts.row_id,
            "parent_session_id": facts.parent_session_id,
            "agent_type": facts.agent_type,
            "claude_session_uuid": facts.claude_session_uuid or None,
        }

    def row_identity(
        self, name: Optional[str], epoch: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        facts = self._get(name, epoch)
        if facts is None or facts.row_id is None:
            return None
        return {
            "id": int(facts.row_id),
            "parent_session_id": facts.parent_session_id,
            "agent_type": facts.agent_type,
            "agent_family": facts.agent_family,
            "agent_family_source": facts.agent_family_source,
        }

    def stored_launch(
        self, name: Optional[str], epoch: Optional[int]
    ) -> StoredLaunch:
        facts = self._get(name, epoch)
        if facts is None:
            return NOT_KNOWN
        if facts.agent_family_source not in DEFINITE_LAUNCH_SOURCES:
            return NOT_KNOWN
        return StoredLaunch(
            known=True, agent_type=facts.agent_type, from_fingerprint=False
        )

    def seed_row(
        self, name: Optional[str], epoch: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """The four columns the STATUS SEED ladder reads, or None.

            ONLY CALL THIS WHEN ``complete`` IS TRUE. On a False index
            every answer here is None, and None from a seed's point of
            view means "this session's instance could not be identified",
            which would blank the whole pass's status ladder rather than
            degrade one decoration. The seam enforces that; this method
            does not, because a method that silently substituted a
            different answer for an incomplete index would be hiding the
            distinction the flag exists to keep.
        Inputs: name (str | None). epoch (int | None).
        Output: dict | None - ``activity_state``, ``activity_state_at``,
            ``claude_session_uuid``, ``working_dir``.
        Example: index.seed_row("cloude_a", 1700000000)
        """
        facts = self._get(name, epoch)
        if facts is None:
            return None
        return {
            "activity_state": facts.activity_state,
            "activity_state_at": facts.activity_state_at,
            "claude_session_uuid": facts.claude_session_uuid,
            "working_dir": facts.working_dir,
        }


def build_instance_index(
    conn, *, socket: str, names: Iterable[str], host_key: str = LOCAL_HOST_KEY
) -> InstanceIndex:
    wanted = [n for n in dict.fromkeys(names) if n]
    if conn is None or not socket:
        return InstanceIndex()
    if not wanted:
        return InstanceIndex(complete=True)

    chunk_size = 400
    facts: Dict[InstanceKey, InstanceFacts] = {}
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        for start in range(0, len(wanted), chunk_size):
            chunk = wanted[start:start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                "SELECT id, parent_session_id, agent_type, agent_family, "
                "agent_family_source, title, tmux_name, tmux_created_epoch, "
                "activity_state, activity_state_at, claude_session_uuid, "
                "working_dir "
                "FROM sessions "
                f"WHERE tmux_socket = ? AND tmux_name IN ({placeholders}) "
                f"AND tmux_created_epoch IS NOT NULL{scope_sql} "
                "ORDER BY id ASC",
                (socket, *chunk, *scope_params),
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                try:
                    key: InstanceKey = (
                        row["tmux_name"], int(row["tmux_created_epoch"])
                    )
                except (TypeError, ValueError, KeyError):
                    continue
                title = _clean_title(row.get("title"))
                existing = facts.get(key)
                if existing is None:
                    facts[key] = InstanceFacts(
                        title=title,
                        row_id=row.get("id"),
                        parent_session_id=row.get("parent_session_id"),
                        agent_type=row.get("agent_type"),
                        agent_family_source=row.get("agent_family_source"),
                        agent_family=row.get("agent_family"),
                        activity_state=row.get("activity_state"),
                        activity_state_at=row.get("activity_state_at"),
                        claude_session_uuid=row.get("claude_session_uuid"),
                        working_dir=row.get("working_dir"),
                    )
                else:
                    facts[key] = InstanceFacts(
                        title=title,
                        row_id=existing.row_id,
                        parent_session_id=existing.parent_session_id,
                        agent_type=existing.agent_type,
                        agent_family_source=existing.agent_family_source,
                        agent_family=existing.agent_family,
                        activity_state=existing.activity_state,
                        activity_state_at=existing.activity_state_at,
                        claude_session_uuid=existing.claude_session_uuid,
                        working_dir=existing.working_dir,
                    )
    except (sqlite3.Error, TypeError, ValueError) as exc:
        logger.warning(
            "instance_index_read_failed",
            extra={"tmux_socket": socket, "error": str(exc)},
        )
        return InstanceIndex()
    return InstanceIndex(facts, complete=True)
