"""Whether a session's notifications are muted, answered without touching disk.

WHAT THIS IS FOR. "mute notifications" on the session action menu is a
durable decision the user makes about ONE session, and two very different
kinds of code have to honour it: the hook route, which decides whether to
raise a web alert, and the push dispatcher, which decides whether to send
a phone notification. Both run where an SQLite open would be felt - the
hook route is on the critical path of a live working session, and the
dispatcher drains a queue on the event loop - so neither may read the
database to answer the question. This module is the in-memory projection
they read instead, hydrated ONCE from
:func:`src.core.session_store.notification_policy_rows` before the
notification producers start, and updated in place by the one writer.

THREE VALUES, AND ``unknown`` IS NOT A FLAVOUR OF ``unmuted``. That
distinction is the whole reason this file exists rather than a boolean on
``SessionManager``:

  ``muted``    the row was read and says the user muted this session.
  ``unmuted``  the row was read and says nothing is muted, OR there is no
               row at all. Both are DEFINITE: a mute can only ever be
               recorded on a session row (schema v26), so a session with
               no row has demonstrably never been muted.
  ``unknown``  the policy has never been read successfully. Nothing is
               known about ANY session, because hydration is one bulk
               query.

A FAILED READ MAY NOT ANSWER "NOT MUTED", and this is deliberately the
opposite posture from the sub-agent toast gate next to it in the hook
route. That gate FAILS TOWARD NOTIFYING, because silence there would be
bought with no evidence and a missed "your turn" is worse than a spurious
one. Here the user has made an explicit standing request to be left
alone, and answering "we could not check, so we assumed you did not mean
it" turns a database hiccup into a stream of pushes the user told us not
to send - to a phone, irreversibly. So ``unknown`` SUPPRESSES, and it says
so in the log every time (``notification_policy_unknown``) rather than
passing for a normal quiet moment.

THE BLAST RADIUS OF THAT IS BOUNDED AND WORTH STATING PLAINLY. ``unknown``
is reached only when the ONE bulk hydration query has never succeeded -
an install whose datastore cannot be opened or read at all. An install
with no datastore FILE is not that case: there are no rows, so nothing can
be muted, and hydration of an absent database succeeds with an empty
index. Callers are expected to retry hydration (see
:meth:`NotificationPolicyStore.needs_hydration`), so the first successful
read ends the condition for good.

THE GENERATION IS A COUNTER, NOT A CLOCK. Every policy change steps it by
one, mute and unmute alike. The notification engine does not stamp it: it
asks the live verdict again right before every send, so an alert queued
before a mute never arrives after it.

KEYED BY ``session_uuid``, WITH AN INSTANCE INDEX IN FRONT OF IT. The
durable identity of a session is its uuid; what a live caller has to hand
is a tmux name and, usually, a creation epoch. Both keys are built from
the same bulk read, so they can never disagree. The name-only fallback is
the lossy one and is used only when the epoch is genuinely unavailable -
see :meth:`NotificationPolicyStore.for_instance`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

import structlog

logger = structlog.get_logger()

POLICY_MUTED = "muted"

POLICY_UNMUTED = "unmuted"

POLICY_UNKNOWN = "unknown"

ALL_POLICY_VERDICTS: Tuple[str, ...] = (
    POLICY_MUTED,
    POLICY_UNMUTED,
    POLICY_UNKNOWN,
)

@dataclass(frozen=True)
class PolicyVerdict:

    verdict: str
    session_uuid: Optional[str] = None
    generation: Optional[int] = None

    @property
    def suppresses(self) -> bool:
        return self.verdict != POLICY_UNMUTED

    @property
    def muted(self) -> bool:
        return self.verdict == POLICY_MUTED


UNKNOWN_VERDICT = PolicyVerdict(verdict=POLICY_UNKNOWN)


@dataclass(frozen=True)
class _PolicyRecord:

    session_uuid: str
    muted: bool
    generation: int


class NotificationPolicyStore:

    def __init__(self) -> None:
        self._by_uuid: Dict[str, _PolicyRecord] = {}
        self._by_instance: Dict[Tuple[str, int], str] = {}
        self._by_name: Dict[str, str] = {}
        self._hydrated: bool = False

    @property
    def hydrated(self) -> bool:
        return self._hydrated

    def needs_hydration(self) -> bool:
        return not self._hydrated

    def hydrate(self, rows: Iterable[Dict[str, Any]]) -> int:
        by_uuid: Dict[str, _PolicyRecord] = {}
        by_instance: Dict[Tuple[str, int], str] = {}
        by_name: Dict[str, str] = {}
        for row in rows:
            session_uuid = row.get("session_uuid")
            if not session_uuid:
                continue
            record = _PolicyRecord(
                session_uuid=str(session_uuid),
                muted=bool(row.get("muted")),
                generation=int(row.get("generation") or 0),
            )
            by_uuid[record.session_uuid] = record
            name = row.get("tmux_name")
            epoch = row.get("tmux_created_epoch")
            if name:
                by_name[str(name)] = record.session_uuid
                if epoch is not None:
                    try:
                        by_instance[(str(name), int(epoch))] = record.session_uuid
                    except (TypeError, ValueError):
                        pass
        self._by_uuid = by_uuid
        self._by_instance = by_instance
        self._by_name = by_name
        self._hydrated = True
        return len(by_uuid)

    def apply(self, session_uuid: str, *, muted: bool, generation: int) -> None:
        if not session_uuid:
            return
        record = _PolicyRecord(
            session_uuid=str(session_uuid),
            muted=bool(muted),
            generation=int(generation),
        )
        updated = dict(self._by_uuid)
        updated[record.session_uuid] = record
        self._by_uuid = updated

    def bind_instance(
        self,
        session_uuid: str,
        *,
        tmux_name: Optional[str],
        tmux_created_epoch: Optional[int],
    ) -> None:
        if not session_uuid or not tmux_name:
            return
        names = dict(self._by_name)
        names[str(tmux_name)] = str(session_uuid)
        self._by_name = names
        if tmux_created_epoch is None:
            return
        try:
            key = (str(tmux_name), int(tmux_created_epoch))
        except (TypeError, ValueError):
            return
        instances = dict(self._by_instance)
        instances[key] = str(session_uuid)
        self._by_instance = instances

    def for_uuid(self, session_uuid: Optional[str]) -> PolicyVerdict:
        if not self._hydrated:
            return UNKNOWN_VERDICT
        if not session_uuid:
            return PolicyVerdict(verdict=POLICY_UNMUTED, generation=0)
        record = self._by_uuid.get(str(session_uuid))
        if record is None:
            return PolicyVerdict(
                verdict=POLICY_UNMUTED,
                session_uuid=str(session_uuid),
                generation=0,
            )
        return PolicyVerdict(
            verdict=POLICY_MUTED if record.muted else POLICY_UNMUTED,
            session_uuid=record.session_uuid,
            generation=record.generation,
        )

    def for_instance(
        self,
        tmux_name: Optional[str],
        tmux_created_epoch: Optional[int] = None,
    ) -> PolicyVerdict:
        if not self._hydrated:
            return UNKNOWN_VERDICT
        if not tmux_name:
            return PolicyVerdict(verdict=POLICY_UNMUTED, generation=0)
        session_uuid: Optional[str] = None
        if tmux_created_epoch is not None:
            try:
                session_uuid = self._by_instance.get(
                    (str(tmux_name), int(tmux_created_epoch))
                )
            except (TypeError, ValueError):
                session_uuid = None
        else:
            session_uuid = self._by_name.get(str(tmux_name))
        return self.for_uuid(session_uuid)


def hydrate_from_datastore(
    store: NotificationPolicyStore, db_path
) -> bool:
    """Read every row's policy into ``store``. The ONE io seam.

    Description: kept apart from the store itself so every rule above
      stays testable without a database, and so there is exactly one
      place that decides what counts as a SUCCESSFUL read.

      A MISSING DATABASE FILE IS A SUCCESS, NOT A FAILURE, and the
      difference matters more than it looks. No file means no session
      rows, and no session rows means nothing can be muted - so "nothing
      is muted" is a measurement there, not an assumption, and a fresh
      install must not start life suppressing every notification it has.
      A file that exists and cannot be opened or queried is the opposite
      case: the answer is unavailable, the store stays unhydrated, and
      every verdict is ``unknown`` until a later attempt succeeds.

      NEVER RAISES. Boot must not fail because a policy could not be
      read, and the unhydrated state already reports the failure
      truthfully to every caller.
    Inputs: store (NotificationPolicyStore) - hydrated in place.
      db_path (pathlib.Path) - the datastore file.
    Output: bool - True when the store is now hydrated.
    Example: hydrate_from_datastore(store, Path('cloude.db'))
    """
    from contextlib import closing

    from src.core import session_store
    from src.core.db import DatastoreUnreadableError, connect

    try:
        if db_path is None or not db_path.exists():
            store.hydrate([])
            logger.info("notification_policy_hydrated", rows=0, datastore=False)
            return True
    except OSError as exc:
        logger.warning(
            "notification_policy_hydrate_failed",
            error=str(exc),
            stage="stat",
        )
        return False

    try:
        with closing(connect(db_path, create=False)) as conn:
            rows = session_store.notification_policy_rows(conn)
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning(
            "notification_policy_hydrate_failed",
            error=str(exc),
            stage="read",
        )
        return False

    count = store.hydrate(rows)
    muted = sum(1 for row in rows if row.get("muted"))
    logger.info(
        "notification_policy_hydrated",
        rows=count,
        muted=muted,
        datastore=True,
    )
    return True
