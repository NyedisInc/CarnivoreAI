
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
