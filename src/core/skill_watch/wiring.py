
from __future__ import annotations

import json
from typing import Any, Callable, Sequence

import structlog

from src.core import session_change_notice
from src.core.attention.raise_gate import resolve_raise
from src.core.skill_fires.tally import default_store
from src.core.skill_watch.store import default_watch_store
from src.core.skill_watch.attribution import SkillAttribution
from src.core.skill_watch.tripwire import TripwireFinding, TripwireProbe, notice_copy
from src.models import ToastNewMessage

logger = structlog.get_logger(__name__)


def attach_tripwire(reader: Any, app_state: Any) -> None:
    services = getattr(app_state, "services", None)
    if services is None:
        return
    attribution = SkillAttribution(services)
    reader.set_skill_probe(TripwireProbe(default_store(), default_watch_store(), attribution.disclosed,
                                         dynamic=attribution.dynamic))


def make_notice_raiser(manager: Any, app_state: Any, send: Callable[[str, str], None],
                       ) -> Callable[[Any, Sequence[TripwireFinding]], None]:
    announced: set = set()

    def raise_notice(target: Any, findings: Sequence[TripwireFinding]) -> None:
        findings = [f for f in findings if (target.session_id, f) not in announced]
        if not findings:
            return
        announced.update((target.session_id, f) for f in findings)
        try:
            gate = resolve_raise(
                "Notification",
                policy_store_attached=getattr(manager, "_notification_policy_store", None) is not None,
                policy=manager.notification_policy_stamp(target.session_id))
            if not gate.raises_toast:
                return
            title, body = notice_copy(findings)
            toast = manager.record_toast(session_id=target.session_id, kind="Notification",
                                         title=title, body=body, notify_type="session.skill_tripwire")
            payload = ToastNewMessage(toast=toast).model_dump_json()
            send(target.session_id, payload)
            session_change_notice.publish(app_state, json.loads(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill_tripwire_notice_failed", error_type=type(exc).__name__)
    return raise_notice
