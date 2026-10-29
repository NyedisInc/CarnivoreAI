"""Which tmux sessions this app created, and the file that remembers it.

Slice S3 of ``.claude/notes/backend-decomposition-plan.md``. This module
holds ``OwnedTmuxLedger``, the single owner of ``owned_tmux_sessions`` -
the set of full tmux session names Cloude Code itself created - together
with ``session_metadata.json``, which is that set's only durable home,
and the two ownership queries answered from ``cloude.db``.

**OWNERSHIP IS THE BADGE, AND A WRONG ANSWER IS SPOOFABLE.** The set
exists so the UI can tell OUR sessions apart from the user's own tmux
sessions on the same ``-L cloude`` socket, without falling back to a
prefix match on the name, which anybody can imitate by naming a session
``cloude_anything``. Everything here is therefore keyed on a name this
app RECORDED, or on an instance triple the datastore RECORDED, and never
on the shape of a string.

**THE SET IS ALSO THE FILE, AND THE FILE ALSO HOLDS A SESSION POINTER.**
``session_metadata.json`` carries two unrelated things: the owned set,
which is about EVERY session this app created, and one session's row,
which is about the single most-recently-active one. Unlinking the file to
discard a dead pointer threw away N sessions' ownership record to clean
up one, and the trigger was the ORDINARY case rather than an error path.
``drop_session_pointer`` is what keeps them apart: the pointer dies, the
set is re-written.

**THE WRITE IS ATOMIC AND IT MATTERS.** ``write_atomic`` is the tmp plus
``fsync`` plus ``os.replace`` protocol, and it is the reason a crash
mid-write cannot leave a zero-byte file where the ownership record was.
``tests/test_owned_tmux_ledger.py`` mutates that protocol away and
measures the result rather than trusting the reading.

**THE SOCKET ARRIVES THE SAME WAY, AND THAT IS NOT SYMMETRY FOR ITS OWN
SAKE.** ``SessionManager._tmux_socket_name`` resolves the configured
value and then lets the PROBED socket win over it, because a row is
written keyed on the socket the adopt path saw and read back keyed on
whatever the badge asks for; if those two ever differ, the badge is
answered from a socket nothing was written to and every adopted session
reads as external. That preference is the manager's to express, so this
class asks for the answer rather than deriving one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from src.core.db_reuse.change_cache import ChangeCache, main_file
from src.core.unique_tmp_path import unique_tmp_path

from src.core.sessions.ports import SessionRecordStore

# could not
DB_INSTANCES_UNSET: Any = object()

logger = structlog.get_logger()

_OWNED_READS = ChangeCache()


class MetadataLoad:

    __slots__ = ("session", "owned_count")

    def __init__(self, *, session: Optional[dict[str, Any]], owned_count: int) -> None:
        self.session = session
        self.owned_count = owned_count


class OwnedTmuxLedger:
    """Owns the owned-tmux-name set, its file, and the ownership queries.

    Description: ``SessionManager`` holds one of these and keeps NO copy
      of the set. Every reader and every writer inside the manager
      reaches ``ledger.names`` itself, so the two can never disagree. Two
      objects holding one logical set and kept in sync by hand is the
      shape of the bug that produced 22 ``/sessions/list`` rows for 21
      live panes.
    Inputs: metadata_path (Callable[[], Path]) - where
      ``session_metadata.json`` lives, resolved at each call so a test
      that moves the state directory is followed. records
      (SessionRecordStore) - how ``cloude.db`` is reached. socket_name
      (Callable[[], str]) - the tmux socket stored instance triples are
      keyed on, resolved at each call for the same reason.
    Output: none.
    Example: OwnedTmuxLedger(metadata_path=reader.session_metadata_path,
      records=store, socket_name=manager.tmux_socket_name)

    THE THREE PIECES OF STATE ARE HERE FOR THREE DIFFERENT REASONS and
    are not interchangeable. ``names`` is the durable record.
    ``needs_legacy_backfill`` is a one-shot upgrade sentinel for a pre-v3
    file that has no owned set in it at all. ``boot_listing`` is neither
    durable nor a sentinel: it is the tmux listing the boot reconcile
    measured, held so the re-adopt pass that runs after it can be GATED
    on a probe having actually answered. It sits here because the only
    thing it is ever used for is deciding what may be claimed as ours.
    """

    def __init__(
        self,
        *,
        metadata_path: Callable[[], Path],
        records: SessionRecordStore,
        socket_name: Callable[[], str],
    ) -> None:
        self._metadata_path = metadata_path
        self._records = records
        self._socket_name = socket_name

        self.names: set[str] = set()

        self.needs_legacy_backfill: bool = False

        self.boot_listing: Any = None


    def path(self) -> Path:
        """Where ``session_metadata.json`` is right now.

        Description: resolved on every call rather than cached, because
          the state directory moves under a test and relocates itself out
          of the legacy log directory on the next write.
        Inputs: none.
        Output: Path.
        Example: ledger.path().exists()
        """
        return self._metadata_path()

    def write_atomic(self, data: dict) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = unique_tmp_path(path)

        try:
            with tmp.open("w") as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError as exc:
                    logger.debug("metadata_fsync_unsupported", error=str(exc))

            os.replace(str(tmp), str(path))
        except OSError:
            # state directory
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def load(self) -> MetadataLoad:
        metadata_path = self.path()

        if not metadata_path.exists():
            logger.info("no_existing_session_metadata")
            return MetadataLoad(session=None, owned_count=len(self.names))

        try:
            with open(metadata_path, "r") as f:
                raw = json.load(f)

            owned = raw.pop("owned_tmux_sessions", None)

            if not raw.get("id"):
                self.names = set(owned or [])
                self.needs_legacy_backfill = False
                logger.info(
                    "session_metadata_owned_set_only_loaded",
                    owned_count=len(self.names),
                    note="no persisted session to rehydrate",
                )
                return MetadataLoad(session=None, owned_count=len(self.names))

            if owned is None:
                self.names = set()
                self.needs_legacy_backfill = True
                logger.info(
                    "session_metadata_legacy_detected",
                    session_id=raw.get("id"),
                    note="owned_tmux_sessions will be backfilled on rehydrate",
                )
            else:
                self.names = set(owned)
                self.needs_legacy_backfill = False

            return MetadataLoad(session=raw, owned_count=len(self.names))
        except (OSError, ValueError, TypeError) as exc:
            logger.error("failed_to_load_session_metadata", error=str(exc))
            return MetadataLoad(session=None, owned_count=len(self.names))

    def save(self, payload: dict) -> bool:
        try:
            payload["owned_tmux_sessions"] = sorted(self.names)
            self.write_atomic(payload)
            self.needs_legacy_backfill = False
            logger.debug(
                "session_metadata_saved",
                session_id=payload.get("id"),
                owned_count=len(self.names),
            )
            return True
        except (OSError, ValueError, TypeError) as exc:
            logger.error("failed_to_save_session_metadata", error=str(exc))
            return False

    def drop_session_pointer(self) -> None:
        metadata_path = self.path()
        try:
            if metadata_path.exists():
                metadata_path.unlink()
                logger.info("stale_session_metadata_deleted")
            if self.names:
                self.write_atomic({"owned_tmux_sessions": sorted(self.names)})
                logger.info(
                    "stale_session_metadata_owned_set_kept",
                    owned_count=len(self.names),
                )
        except (OSError, ValueError, TypeError) as exc:
            logger.error("failed_to_delete_stale_metadata", error=str(exc))


    def instances_from_db(self) -> Optional[set]:
        """The owned ``(tmux_name, epoch)`` pairs recorded in ``cloude.db``.

        Description: the single datastore read behind every ownership
          decision. Keyed on the INSTANCE, never on the name alone, so a
          reused tmux name cannot inherit a dead session's badge.
        Inputs: none.
        Output: set[tuple[str, int]] | None - None when the datastore
          could not answer at all (absent, unreadable, pre-v2). An EMPTY
          SET is a real answer, "the datastore knows of no owned
          instance", and every caller treats the two differently.
        Example: owned = ledger.instances_from_db()
        """
        socket = self._socket_name()
        found = _OWNED_READS.fetch_opened(self._records, ("owned_instances", socket), lambda: self._read_instances(socket))
        return None if found is None else set(found)

    def _read_instances(self, socket: str) -> tuple:
        conn = self._records.read_connection()
        if conn is None:
            return None, None
        try:
            from src.core.session_store import owned_instances, sessions_table_ready

            if not sessions_table_ready(conn):
                return None, None
            return frozenset(owned_instances(conn, socket=socket)), main_file(conn)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ownership_db_read_failed", error=str(exc))
            return None, None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def instances(self) -> Optional[set]:
        """Owned ``(tmux_name, epoch)`` pairs, and only those.

        Description: the value handed to the attachable listing, which is
          the one path that HAS the epoch for every row and can therefore
          make the identity-correct decision.

          THE LEGACY NAME SET IS DELIBERATELY NOT FOLDED IN HERE. It used
          to be, as ``(name, None)``, and the backend read a None epoch as
          a NAME-ONLY WILDCARD. That disabled the epoch tier for every
          session this app had created since the last restart - precisely
          the population the epoch exists to protect - so a dead
          ``cloude_work`` replaced by the user's own unrelated
          ``cloude_work`` badged as ours, exactly as it did before the
          epoch existed. The legacy names still reach the backend, but as
          the SEPARATE ``owned_names`` argument, resolved at their own,
          lower, explicitly name-only tier where they can never override a
          stored epoch. See
          :func:`src.core.tmux_listing_parse.resolve_ownership`.
        Inputs: none.
        Output: set[tuple[str, int]] | None - None when the datastore
          could not answer at all.
        Example: ledger.instances()
        """
        from_db = self.instances_from_db()
        if from_db is None:
            return None
        return set(from_db)

    def is_owned_name(self, name: Optional[str], *, db_instances: Any = DB_INSTANCES_UNSET) -> bool:
        """Report whether a tmux NAME belongs to a session we own.

        Description: the name-only fallback, for call sites that carry no
          creation epoch - ``SessionInfo`` is one. Lossy in exactly one
          way, stated so nobody has to rediscover it: a name owned as one
          instance and now reused by a different, unowned instance reads
          as owned here until the epoch reaches that call site. The
          attachable listing, which does have the epoch, is not lossy.
        Inputs: name (str | None) - a tmux session name.
          db_instances (set | None, keyword) - ONE :meth:`instances_from_db`
          answer a listing pass read once and lends to every row, so the
          pass opens the datastore once instead of once per row. Omitted,
          the read is made here, as before; None keeps its meaning
          "the datastore could not answer".
        Output: bool - False for None or an empty name.
        Example: ledger.is_owned_name('cloude_a')
        """
        if not name:
            return False
        if name in self.names:
            return True
        from_db = self.instances_from_db() if db_instances is DB_INSTANCES_UNSET else db_instances
        if from_db is None:
            return False
        return any(owned_name == name for owned_name, _epoch in from_db)
