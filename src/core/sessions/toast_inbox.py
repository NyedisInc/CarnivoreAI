
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, Tuple

import structlog

from src.core import resource_push
from src.core.resource_push.topics import TOASTS as TOASTS_TOPIC
from src.models import Toast
from src.models.notifications import ToastDetail
from src.models.utc_time import as_aware_utc, utc_now

logger = structlog.get_logger()


class ToastInbox:

    ACKED_CAP = 50

    SUPERSEDING_KINDS = frozenset({"Stop"})

    def __init__(self) -> None:
        self.pending: dict[str, List[Toast]] = {}


    def has(self, session_id: str) -> bool:
        return session_id in self.pending

    def bucket(self, session_id: str) -> List[Toast]:
        return self.pending.get(session_id, [])

    def get(self, session_id: str, unacked_only: bool = False) -> List[Toast]:
        bucket = self.pending.get(session_id, [])
        if unacked_only:
            return [t for t in bucket if not t.acknowledged]
        return list(bucket)

    def find_supersedable(
        self, bucket: Sequence[Toast], kind: str, title: str
    ) -> Optional[Toast]:
        if kind not in self.SUPERSEDING_KINDS:
            return None
        for existing in bucket:
            if (
                existing.kind == kind
                and not existing.acknowledged
                and existing.title == title
            ):
                return existing
        return None


    def store(
        self,
        session_id: str,
        *,
        kind: str,
        title: str,
        body: Optional[str],
        color: Optional[str],
        session_label: Optional[str],
        session_name: Optional[str],
        notify_type: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Tuple[Toast, bool]:
        import uuid as _uuid

        stamp = as_aware_utc(now) if now is not None else utc_now()
        bucket = self.pending.setdefault(session_id, [])
        superseded = self.find_supersedable(bucket, kind, title)
        if superseded is not None:
            content_changed = (
                superseded.body != body
                or superseded.color != color
                or superseded.session_label != session_label
                or superseded.session_name != session_name
            )
            superseded.body = body
            superseded.color = color
            superseded.session_label = session_label
            superseded.session_name = session_name
            superseded.created_at = stamp
            superseded.notify_type = notify_type
            if content_changed:
                superseded.version += 1
            bucket.remove(superseded)
            bucket.insert(0, superseded)
            toast = superseded
            was_superseded = True
            logger.info(
                "toast_superseded",
                session_id=session_id,
                toast_id=toast.id,
                kind=kind,
                version=toast.version,
            )
        else:
            toast = Toast(
                id=_uuid.uuid4().hex,
                session_id=session_id,
                kind=kind,
                title=title,
                body=body,
                color=color,
                session_label=session_label,
                session_name=session_name,
                notify_type=notify_type,
                created_at=stamp,
                acknowledged=False,
            )
            bucket.insert(0, toast)
            was_superseded = False
            logger.info(
                "toast_recorded",
                session_id=session_id,
                toast_id=toast.id,
                kind=kind,
                color=color,
            )
        self.prune(session_id)
        resource_push.notify(TOASTS_TOPIC)
        return toast, was_superseded

    def describe(
        self, session_id: str, toast_id: str, detail: Optional[ToastDetail]
    ) -> Optional[Toast]:
        for toast in self.pending.get(session_id, []):
            if toast.id != toast_id:
                continue
            if not toast.acknowledged and toast.detail != detail:
                toast.detail = detail
                toast.version += 1
            return toast
        return None

    def ack(self, session_id: str, toast_id: str, reason: str) -> bool:
        bucket = self.pending.get(session_id)
        if not bucket:
            return False
        for t in bucket:
            if t.id == toast_id:
                if t.acknowledged:
                    return False
                t.acknowledged = True
                t.ack_reason = reason
                t.version += 1
                self.prune(session_id)
                logger.info(
                    "toast_acked",
                    session_id=session_id,
                    toast_id=toast_id,
                    reason=reason,
                    version=t.version,
                )
                resource_push.notify(TOASTS_TOPIC)
                return True
        return False

    def prune(self, session_id: str) -> None:
        toasts = self.pending.get(session_id)
        if not toasts:
            return
        acked_count = 0
        keep: List[Toast] = []
        for t in toasts:
            if t.acknowledged:
                if acked_count < self.ACKED_CAP:
                    keep.append(t)
                    acked_count += 1
            else:
                keep.append(t)
        self.pending[session_id] = keep

    def drop_session(self, session_id: str) -> None:
        dropped = self.pending.pop(session_id, None)
        if dropped and any(not t.acknowledged for t in dropped):
            resource_push.notify(TOASTS_TOPIC)
