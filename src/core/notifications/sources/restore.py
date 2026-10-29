
from __future__ import annotations

from typing import Optional

from src.core.notifications.sources import common
from src.core.notifications import contracts

TYPE_ID = "app.restore_offer"

_announced = False


def on_offered(offer_id: Optional[str]) -> bool:
    global _announced
    if _announced:
        return False
    sent = common.emit_if_sink(contracts.NotifyEvent(
        type_id=TYPE_ID, kind="restore_offer", title=common.type_title(TYPE_ID), ts=common.now(),
        instance_key=f"restore:{offer_id or 'boot'}",
    ))
    _announced = sent
    return sent


def reset_for_tests() -> None:
    global _announced
    _announced = False
